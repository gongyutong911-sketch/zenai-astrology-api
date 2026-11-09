import logging
import os
import re
import secrets
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from astrology_engine import (
    FREE_FIELDS,
    GUIDANCE_FIELDS,
    GuidanceOutputError,
    GuidanceRateLimited,
    GuidanceUnavailable,
    get_astrology_energy_guidance,
)
from database import (
    ConflictingIdentity,
    DeepReportLocked,
    IdempotencyConflict,
    IdempotencyInProgress,
    InvalidMembership,
    UnknownUser,
    HISTORY_TIERS,
    TIER_FREE,
    abort_idempotency,
    apply_plan,
    authorize_deep_report,
    claim_idempotency,
    combine_identity,
    complete_idempotency,
    grant_deep_credits,
    guidance_for_storage,
    list_readings,
    membership_view,
    present_reading,
    remember_reading,
    resolve_member,
    restore_deep_credit,
    subscription_expired,
)
from fulfillment import (
    InputRejected,
    RateLimited,
    copy_text,
    enforce_rate_limit,
    fingerprint,
    guidance_is_usable,
    idempotency_scope,
    key_hint,
    localize,
    log_event,
    negotiate_locale,
    normalize_deep,
    normalize_energy,
    parse_idempotency_key,
    rate_bucket,
    redact_birth_date,
    redact_birth_time,
    redact_question,
)
from bazi import compose_deep_report

STATIC_DIR = Path(__file__).resolve().parent / "static"

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] request_id=%(request_id)s %(message)s"


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _HealthCheckAccessFilter(logging.Filter):
    """丢掉 GET / 的访问日志，避免 Render 存活探测刷屏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET / ' not in record.getMessage()


def configure_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(_RequestIdFilter())
    handler._zenai_log = True
    for name in ("main", "astrology_engine", "database", "fulfillment"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        if not any(getattr(existing, "_zenai_log", False) for existing in log.handlers):
            log.addHandler(handler)
        log.propagate = False
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _HealthCheckAccessFilter) for item in access_logger.filters):
        access_logger.addFilter(_HealthCheckAccessFilter())


configure_logging()
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI(
    title="ZenAI Astrology & Energy API",
    description="An AI-powered astrology and energy guidance API.",
    version="1.0.0"
)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = incoming if _REQUEST_ID.fullmatch(incoming or "") else uuid.uuid4().hex[:16]
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-Id"] = request_id
    return response


@app.on_event("startup")
def configure_runtime_logging() -> None:
    configure_logging()


def _test_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/")
def read_root(request: Request):
    # 浏览器打开首页时返回测试页；不带 text/html 的探测仍返回 JSON，供 Render 存活检查使用。
    if "text/html" in request.headers.get("accept", ""):
        return _test_page()
    return {"status": "ok", "message": "ZenAI Astrology & Energy API is running smoothly!"}


@app.get("/ui", include_in_schema=False)
def test_ui():
    return _test_page()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _locale(request: Request) -> str:
    return negotiate_locale(request.headers.get("accept-language"))


def _client_host(request: Request) -> Optional[str]:
    if request.client is None:
        return None
    return request.client.host


def _domain_error(exc: Exception, locale: str) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, UnknownUser):
        return HTTPException(status_code=404, detail=localize(locale, str(exc)))
    if isinstance(exc, InputRejected):
        return HTTPException(status_code=400, detail=copy_text(locale, exc.code))
    if isinstance(exc, IdempotencyConflict):
        return HTTPException(status_code=409, detail=copy_text(locale, "idempotency_conflict"))
    if isinstance(exc, IdempotencyInProgress):
        return HTTPException(status_code=409, detail=copy_text(locale, "idempotency_in_progress"))
    if isinstance(exc, GuidanceOutputError):
        return HTTPException(
            status_code=502,
            detail={"code": "model_output", "message": copy_text(locale, "model_output")},
        )
    if isinstance(exc, (ConflictingIdentity, InvalidMembership, ValueError)):
        return HTTPException(status_code=400, detail=localize(locale, str(exc)))
    if isinstance(exc, RateLimited):
        return HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": copy_text(locale, "rate_limited")},
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, GuidanceRateLimited):
        retry_after = 2 if exc.retry_after is None else max(1, min(120, int(exc.retry_after + 0.999)))
        return HTTPException(
            status_code=429,
            detail={"code": "model_rate_limited", "message": copy_text(locale, "model_rate_limited")},
            headers={"Retry-After": str(retry_after)},
        )
    if isinstance(exc, GuidanceUnavailable):
        return HTTPException(
            status_code=503,
            detail={"code": "model_unavailable", "message": copy_text(locale, "model_unavailable")},
        )
    return HTTPException(
        status_code=500,
        detail={"code": "internal", "message": copy_text(locale, "internal")},
    )


def _release_idempotency(scope: Optional[str], idempotency_key: Optional[str]) -> None:
    if scope and idempotency_key:
        abort_idempotency(scope=scope, idempotency_key=idempotency_key)


def _replay_response(replay: dict):
    response = JSONResponse(replay["body"], status_code=replay["status_code"])
    response.headers["Idempotency-Replay"] = "true"
    return response


# 定义请求体数据结构
class EnergyRequest(BaseModel):
    birth_date: str
    birth_time: str = "12:00"
    gender: str = "female"
    question: str = "今日能量指引"
    user_id: Optional[int] = None
    user_token: Optional[str] = None

class EnergyGuidance(BaseModel):
    core_energy: Optional[str] = None
    career_guidance: Optional[str] = None
    relationship_advice: Optional[str] = None
    wealth_flow: Optional[str] = None
    action_tips: Optional[str] = None
    lucky_elements: Optional[str] = None


EnergyGuidanceResponse = EnergyGuidance


class MembershipStatus(BaseModel):
    tier: str
    is_subscriber: bool
    label: str
    access: str
    unlocked_fields: list[str]
    locked_fields: list[str]
    history_unlocked: bool
    expires_at: Optional[datetime] = None
    message: str


class EnergyResponse(BaseModel):
    status: str
    data: EnergyGuidance
    user_id: int
    user_token: str
    reading_id: int
    one_time_credits: int = 0
    membership: MembershipStatus


class UserProfile(BaseModel):
    id: int
    token: str
    birth_date: str
    birth_time: str
    gender: str
    created_at: datetime
    membership_tier: str
    is_subscriber: bool
    expires_at: Optional[datetime] = None
    one_time_credits: int = 0


class ReadingRecord(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    birth_date: str
    birth_time: str
    gender: str
    question: str
    core_energy: Optional[str] = None
    career_guidance: Optional[str] = None
    relationship_advice: Optional[str] = None
    wealth_flow: Optional[str] = None
    action_tips: Optional[str] = None
    lucky_elements: Optional[str] = None


class HistoryResponse(BaseModel):
    status: str
    user: UserProfile
    membership: MembershipStatus
    data: list[ReadingRecord]


class CheckoutRequest(BaseModel):
    plan_type: str
    user_id: Optional[int] = None
    user_token: Optional[str] = None


class CheckoutResponse(BaseModel):
    status: str
    user_id: int
    user_token: str
    membership: MembershipStatus


class DeepCreditRequest(BaseModel):
    quantity: int = 1
    user_id: Optional[int] = None
    user_token: Optional[str] = None


class DeepCreditResponse(BaseModel):
    status: str
    user_id: int
    user_token: str
    one_time_credits: int
    membership: MembershipStatus


class DeepReportRequest(BaseModel):
    birth_date: str
    birth_time: str = "12:00"
    gender: str = "female"
    question: str = "想看清此刻的处境"
    birth_city: Optional[str] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    zi_hour_mode: str = "early"
    user_id: Optional[int] = None
    user_token: Optional[str] = None


class BaziPillar(BaseModel):
    gan_zhi: str
    gan: str
    zhi: str
    wu_xing: str
    shi_shen: str


class BaziPillars(BaseModel):
    year: BaziPillar
    month: BaziPillar
    day: BaziPillar
    hour: BaziPillar


class BaziStrength(BaseModel):
    score: int
    label: str
    factors: list[str]


class DaYunStep(BaseModel):
    start_age: int
    start_year: int
    gan_zhi: str


class BaziChartModel(BaseModel):
    solar: str
    clock_time: str
    true_solar_time: str
    longitude: float
    latitude: Optional[float] = None
    birth_city: Optional[str] = None
    longitude_offset_minutes: float
    equation_of_time_minutes: float
    zi_hour_mode: str
    zi_hour_label: str
    month_jie: str
    month_jie_at: str
    gender_label: str
    day_master: str
    pillars: BaziPillars
    strength: BaziStrength
    da_yun_start_age: int
    da_yun: list[DaYunStep]
    current_da_yun: Optional[str] = None
    liu_nian: str
    age: int


class ReportChapter(BaseModel):
    key: str
    title: str
    body: str


class DeepReportResponse(BaseModel):
    status: str
    product: str
    user_id: int
    user_token: str
    access_via: str
    one_time_credits: int
    chart: BaziChartModel
    chapters: list[ReportChapter]


def require_api_key(request: Request, x_api_key: Optional[str] = Header(default=None)) -> None:
    """未配置 API_SECRET_KEY 时放行；已配置时要求 X-API-Key 完全匹配。"""
    expected = os.getenv("API_SECRET_KEY", "").strip()
    if not expected:
        return
    provided = (x_api_key or "").encode("utf-8")
    secret = expected.encode("utf-8")
    if len(provided) != len(secret) or not secrets.compare_digest(provided, secret):
        logger.warning("auth_failed status_code=401 header_present=%s", bool(x_api_key))
        raise HTTPException(status_code=401, detail=copy_text(_locale(request), "unauthorized"))


def identify_member(
    request: Request,
    x_user_token: Optional[str] = Header(default=None),
    x_user_id: Optional[int] = Header(default=None),
) -> dict:
    """从请求头识别身份。月订阅和年订阅会在这里按 expires_at 懒加载降级。"""
    try:
        return resolve_member(user_id=x_user_id, user_token=x_user_token)
    except (UnknownUser, ConflictingIdentity, InvalidMembership) as exc:
        raise _domain_error(exc, _locale(request)) from exc


def _membership_status(tier: str, expires_at: Optional[datetime] = None) -> MembershipStatus:
    return MembershipStatus.model_validate(membership_view(tier, expires_at))


@app.post(
    "/api/energy-guidance",
    response_model=EnergyResponse,
    response_model_exclude_none=True,
)
def generate_energy_guidance(
    payload: EnergyRequest,
    request: Request,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    started = time.perf_counter()
    locale = _locale(request)
    scope = None
    idempotency_key = None
    try:
        idempotency_key = parse_idempotency_key(request.headers.get("idempotency-key"))
        energy = normalize_energy(
            payload.birth_date,
            payload.birth_time,
            payload.gender,
            payload.question,
        )
        access = combine_identity(member, payload.user_id, payload.user_token)
    except (UnknownUser, ConflictingIdentity, InvalidMembership, InputRejected, ValueError) as exc:
        log_event(
            logging.INFO,
            "request_rejected",
            route="energy-guidance",
            error=type(exc).__name__,
            code=getattr(exc, "code", ""),
        )
        raise _domain_error(exc, locale) from exc
    depth = "full_coaching" if access["access"] == "full_coaching" else "foundation"
    fields = GUIDANCE_FIELDS if depth == "full_coaching" else FREE_FIELDS
    log_event(
        logging.INFO,
        "request_received",
        route="energy-guidance",
        birth_date=redact_birth_date(energy.birth_date),
        birth_time=redact_birth_time(energy.birth_time),
        gender=energy.gender,
        question=redact_question(energy.question),
        tier=access["tier"],
        depth=depth,
        locale=locale,
    )
    request_hash = fingerprint(
        {
            "birth_date": energy.birth_date,
            "birth_time": energy.birth_time,
            "gender": energy.gender,
            "question": energy.question,
            "depth": depth,
        }
    )
    if idempotency_key:
        scope = idempotency_scope(
            "energy-guidance",
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
            idempotency_key=idempotency_key,
        )
        try:
            replay = claim_idempotency(
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except (IdempotencyConflict, IdempotencyInProgress) as exc:
            raise _domain_error(exc, locale) from exc
        if replay:
            log_event(
                logging.INFO,
                "request_replay",
                route="energy-guidance",
                idempotency=key_hint(idempotency_key),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            return _replay_response(replay)
    try:
        enforce_rate_limit(
            rate_bucket(
                user_id=access.get("user_id"),
                user_token=access.get("user_token"),
                api_key=request.headers.get("x-api-key"),
                host=_client_host(request),
            )
        )
        result = get_astrology_energy_guidance(
            birth_date=energy.birth_date,
            birth_time=energy.birth_time,
            gender=energy.gender,
            question=energy.question,
            depth=depth,
        )
        if not guidance_is_usable(result, fields):
            raise GuidanceOutputError("模型未返回内容")
        stored = guidance_for_storage(result, access["tier"])
        guidance = EnergyGuidance.model_validate(
            {field: value for field, value in stored.items() if value}
        )
        saved = remember_reading(
            birth_date=energy.birth_date,
            birth_time=energy.birth_time,
            gender=energy.gender,
            question=energy.question,
            guidance=stored,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except Exception as exc:
        _release_idempotency(scope, idempotency_key)
        status = _domain_error(exc, locale).status_code
        log_event(
            logging.WARNING if status < 500 else logging.ERROR,
            "request_failed",
            route="energy-guidance",
            status_code=status,
            error=type(exc).__name__,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise _domain_error(exc, locale) from exc
    tier = saved["user"]["membership_tier"]
    response = EnergyResponse(
        status="success",
        data=guidance,
        user_id=saved["user"]["id"],
        user_token=saved["user"]["token"],
        reading_id=saved["reading"]["id"],
        one_time_credits=int(saved["user"].get("one_time_credits") or 0),
        membership=_membership_status(tier, saved["user"].get("expires_at")),
    )
    if scope and idempotency_key:
        try:
            complete_idempotency(
                scope=scope,
                idempotency_key=idempotency_key,
                status_code=200,
                body=response.model_dump(mode="json", exclude_none=True),
            )
        except Exception:
            log_event(
                logging.ERROR,
                "idempotency_persist_failed",
                route="energy-guidance",
                idempotency=key_hint(idempotency_key),
            )
    log_event(
        logging.INFO,
        "request_succeeded",
        route="energy-guidance",
        status_code=200,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        user_id=saved["user"]["id"],
        reading_id=saved["reading"]["id"],
        tier=tier,
    )
    return response


@app.get(
    "/api/energy-history",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
def read_energy_history(
    request: Request,
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """按用户 ID 或 Token 查询个人能量记忆，并按当前权益裁剪维度。"""
    locale = _locale(request)
    try:
        access = combine_identity(member, user_id, user_token)
        if not access["known"]:
            raise ValueError("请提供 user_id 或 user_token")
        archive = list_readings(user_id=access["user_id"], user_token=access["user_token"])
    except (UnknownUser, ConflictingIdentity, InvalidMembership, ValueError) as exc:
        raise _domain_error(exc, locale) from exc
    tier = archive["user"]["membership_tier"]
    expires_at = archive["user"].get("expires_at")
    if tier not in HISTORY_TIERS:
        logger.info("history_locked user_id=%s tier=%s", archive["user"]["id"], tier)
        code = "history_expired" if tier == TIER_FREE and subscription_expired(expires_at) else "history_locked"
        message = copy_text(locale, code)
        raise HTTPException(
            status_code=403,
            detail={
                "code": "history_locked",
                "message": message,
                "tier": tier,
                "expires_at": expires_at.isoformat() if isinstance(expires_at, datetime) else expires_at,
                "one_time_credits": int(archive["user"].get("one_time_credits") or 0),
            },
        )
    logger.info(
        "history_read user_id=%s readings=%s tier=%s",
        archive["user"]["id"],
        len(archive["readings"]),
        tier,
    )
    return HistoryResponse(
        status="success",
        user=UserProfile.model_validate(archive["user"]),
        membership=_membership_status(tier, expires_at),
        data=[
            ReadingRecord.model_validate(present_reading(item, tier))
            for item in archive["readings"]
        ],
    )


@app.post("/api/mock-checkout", response_model=CheckoutResponse)
def mock_checkout(
    payload: CheckoutRequest,
    request: Request,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """模拟支付：按 one_time、monthly、yearly 一键写入对应档位。"""
    locale = _locale(request)
    try:
        access = combine_identity(member, payload.user_id, payload.user_token)
        if not access["known"]:
            raise UnknownUser("请先完成一次觉察，再开通方案")
        saved = apply_plan(
            payload.plan_type,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except (UnknownUser, ConflictingIdentity, InvalidMembership) as exc:
        raise _domain_error(exc, locale) from exc
    logger.info(
        "checkout_succeeded user_id=%s tier=%s plan_type=%s",
        saved["user_id"],
        saved["tier"],
        payload.plan_type,
    )
    return CheckoutResponse(
        status="success",
        user_id=saved["user_id"],
        user_token=saved["user_token"],
        membership=_membership_status(saved["tier"], saved.get("expires_at")),
    )


def _known_access(member: dict, user_id: Optional[int], user_token: Optional[str]) -> dict:
    access = combine_identity(member, user_id, user_token)
    if not access["known"]:
        raise UnknownUser("请先完成一次觉察，再使用深度测算")
    return access


@app.post("/api/mock-buy-deep-credit", response_model=DeepCreditResponse)
def mock_buy_deep_credit(
    payload: DeepCreditRequest,
    request: Request,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """模拟购买单次八字深度测算次数，不改变日常能量指引的会员档位。"""
    locale = _locale(request)
    try:
        access = _known_access(member, payload.user_id, payload.user_token)
        saved = grant_deep_credits(
            quantity=payload.quantity,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except (UnknownUser, ConflictingIdentity, InvalidMembership) as exc:
        raise _domain_error(exc, locale) from exc
    logger.info(
        "deep_credit_granted user_id=%s credits=%s",
        saved["user_id"],
        saved["one_time_credits"],
    )
    return DeepCreditResponse(
        status="success",
        user_id=saved["user_id"],
        user_token=saved["user_token"],
        one_time_credits=saved["one_time_credits"],
        membership=_membership_status(saved["tier"], saved.get("expires_at")),
    )


@app.post("/api/deep-report", response_model=DeepReportResponse)
def create_deep_report(
    payload: DeepReportRequest,
    request: Request,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """八字深度测算。先排盘，确认不是空盘后再扣次，避免失败请求吃掉额度。"""
    started = time.perf_counter()
    locale = _locale(request)
    scope = None
    idempotency_key = None
    charged = None
    try:
        idempotency_key = parse_idempotency_key(request.headers.get("idempotency-key"))
        deep = normalize_deep(
            payload.birth_date,
            payload.birth_time,
            payload.gender,
            payload.question,
            payload.birth_city,
            payload.longitude,
            payload.latitude,
            payload.zi_hour_mode,
        )
        access = _known_access(member, payload.user_id, payload.user_token)
    except (UnknownUser, ConflictingIdentity, InvalidMembership, InputRejected, ValueError) as exc:
        log_event(
            logging.INFO,
            "deep_report_rejected",
            error=type(exc).__name__,
            code=getattr(exc, "code", ""),
        )
        raise _domain_error(exc, locale) from exc
    request_hash = fingerprint(
        {
            "birth_date": deep.birth_date,
            "birth_time": deep.birth_time,
            "gender": deep.gender,
            "question": deep.question,
            "birth_city": deep.birth_city,
            "longitude": deep.longitude,
            "latitude": deep.latitude,
            "zi_hour_mode": deep.zi_hour_mode,
        }
    )
    if idempotency_key:
        scope = idempotency_scope(
            "deep-report",
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
            idempotency_key=idempotency_key,
        )
        try:
            replay = claim_idempotency(
                scope=scope,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )
        except (IdempotencyConflict, IdempotencyInProgress) as exc:
            raise _domain_error(exc, locale) from exc
        if replay:
            log_event(
                logging.INFO,
                "deep_report_replay",
                user_id=access.get("user_id"),
                idempotency=key_hint(idempotency_key),
            )
            return _replay_response(replay)
    try:
        enforce_rate_limit(
            rate_bucket(
                user_id=access.get("user_id"),
                user_token=access.get("user_token"),
                api_key=request.headers.get("x-api-key"),
                host=_client_host(request),
            )
        )
        report = compose_deep_report(
            deep.birth_date,
            deep.birth_time,
            deep.gender,
            deep.question,
            longitude=deep.longitude,
            latitude=deep.latitude,
            birth_city=deep.birth_city,
            zi_hour_mode=deep.zi_hour_mode,
        )
        saved = authorize_deep_report(
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
        charged = saved
        response = DeepReportResponse(
            status="success",
            product="deep_bazi",
            user_id=saved["user_id"],
            user_token=saved["user_token"],
            access_via=saved["access_via"],
            one_time_credits=saved["one_time_credits"],
            chart=BaziChartModel.model_validate(report["chart"]),
            chapters=[ReportChapter.model_validate(item) for item in report["chapters"]],
        )
    except DeepReportLocked as exc:
        _release_idempotency(scope, idempotency_key)
        raise HTTPException(
            status_code=403,
            detail={
                "code": "deep_report_locked",
                "message": copy_text(locale, "deep_locked"),
                "one_time_credits": exc.credits,
            },
        ) from exc
    except Exception as exc:
        if charged is not None and charged.get("access_via") == "credit":
            try:
                restore_deep_credit(user_id=charged.get("user_id"), user_token=charged.get("user_token"))
                log_event(
                    logging.WARNING,
                    "deep_credit_refunded",
                    user_id=charged.get("user_id"),
                    error=type(exc).__name__,
                )
            except Exception:
                log_event(
                    logging.ERROR,
                    "deep_credit_refund_failed",
                    user_id=charged.get("user_id"),
                    error=type(exc).__name__,
                )
        _release_idempotency(scope, idempotency_key)
        status = _domain_error(exc, locale).status_code
        log_event(
            logging.WARNING if status < 500 else logging.ERROR,
            "deep_report_failed",
            status_code=status,
            error=type(exc).__name__,
            birth_date=redact_birth_date(deep.birth_date),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        raise _domain_error(exc, locale) from exc
    if scope and idempotency_key:
        try:
            complete_idempotency(
                scope=scope,
                idempotency_key=idempotency_key,
                status_code=200,
                body=response.model_dump(mode="json", exclude_none=True),
            )
        except Exception:
            log_event(
                logging.ERROR,
                "idempotency_persist_failed",
                route="deep-report",
                idempotency=key_hint(idempotency_key),
            )
    log_event(
        logging.INFO,
        "deep_report_succeeded",
        user_id=saved["user_id"],
        access_via=saved["access_via"],
        credits=saved["one_time_credits"],
        birth_date=redact_birth_date(deep.birth_date),
        elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return response
