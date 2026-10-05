import logging
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from astrology_engine import get_astrology_energy_guidance
from bazi import compose_deep_report, normalize_zi_hour, resolve_birth_place
from database import (
    ConflictingIdentity,
    DeepReportLocked,
    InvalidMembership,
    UnknownUser,
    HISTORY_TIERS,
    TIER_FREE,
    apply_plan,
    authorize_deep_report,
    grant_deep_credits,
    membership_view,
    subscription_expired,
    combine_identity,
    guidance_for_storage,
    list_readings,
    present_reading,
    remember_reading,
    resolve_member,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class _HealthCheckAccessFilter(logging.Filter):
    """丢掉 GET / 的访问日志，避免 Render 存活探测刷屏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET / ' not in record.getMessage()


def configure_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    for name in ("main", "astrology_engine", "database"):
        log = logging.getLogger(name)
        log.setLevel(logging.INFO)
        if not any(getattr(existing, "_zenai_log", False) for existing in log.handlers):
            handler._zenai_log = True
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


def _redact_birth_date(value: str) -> str:
    parts = value.strip().split("-")
    if len(parts) == 3 and len(parts[0]) == 4 and parts[0].isdigit():
        return f"{parts[0]}-{parts[1]}-**"
    return "****"


def _redact_birth_time(value: str) -> str:
    hour, _, _minute = value.strip().partition(":")
    if hour.isdigit():
        return f"{hour}:**"
    return "**:**"


def _redact_question(value: str) -> str:
    text = " ".join(value.split())
    if not text:
        return ""
    preview = text[:8] + ("..." if len(text) > 8 else "")
    return f"{preview} (len={len(text)})"

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


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """未配置 API_SECRET_KEY 时放行；已配置时要求 X-API-Key 完全匹配。"""
    expected = os.getenv("API_SECRET_KEY", "").strip()
    if not expected:
        return
    provided = (x_api_key or "").encode("utf-8")
    secret = expected.encode("utf-8")
    if len(provided) != len(secret) or not secrets.compare_digest(provided, secret):
        logger.warning(
            "auth_failed status_code=401 header_present=%s",
            bool(x_api_key),
            stack_info=True,
        )
        raise HTTPException(status_code=401, detail="未授权")


def identify_member(
    x_user_token: Optional[str] = Header(default=None),
    x_user_id: Optional[int] = Header(default=None),
) -> dict:
    """从请求头识别身份。月订阅和年订阅会在这里按 expires_at 懒加载降级。"""
    try:
        return resolve_member(user_id=x_user_id, user_token=x_user_token)
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _membership_status(tier: str, expires_at: Optional[datetime] = None) -> MembershipStatus:
    return MembershipStatus.model_validate(membership_view(tier, expires_at))


@app.post(
    "/api/energy-guidance",
    response_model=EnergyResponse,
    response_model_exclude_none=True,
)
def generate_energy_guidance(
    request: EnergyRequest,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    started = time.perf_counter()
    try:
        access = combine_identity(member, request.user_id, request.user_token)
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    depth = "full_coaching" if access["access"] == "full_coaching" else "foundation"
    logger.info(
        "request_received birth_date=%s birth_time=%s gender=%s question=%s tier=%s depth=%s",
        _redact_birth_date(request.birth_date),
        _redact_birth_time(request.birth_time),
        request.gender,
        _redact_question(request.question),
        access["tier"],
        depth,
    )
    try:
        # 调用 astrology_engine.py 中的核心计算与 AI 生成函数
        result = get_astrology_energy_guidance(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            gender=request.gender,
            question=request.question,
            depth=depth,
        )
        stored = guidance_for_storage(result, access["tier"])
        guidance = EnergyGuidance.model_validate(
            {field: value for field, value in stored.items() if value}
        )
        saved = remember_reading(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            gender=request.gender,
            question=request.question,
            guidance=stored,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ConflictingIdentity as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "request_failed status_code=500 elapsed_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=500, detail=str(exc))
    tier = saved["user"]["membership_tier"]
    logger.info(
        "request_succeeded status_code=200 elapsed_ms=%.1f user_id=%s reading_id=%s tier=%s",
        (time.perf_counter() - started) * 1000,
        saved["user"]["id"],
        saved["reading"]["id"],
        tier,
    )
    return EnergyResponse(
        status="success",
        data=guidance,
        user_id=saved["user"]["id"],
        user_token=saved["user"]["token"],
        reading_id=saved["reading"]["id"],
        one_time_credits=int(saved["user"].get("one_time_credits") or 0),
        membership=_membership_status(tier, saved["user"].get("expires_at")),
    )


@app.get(
    "/api/energy-history",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
def read_energy_history(
    user_id: Optional[int] = None,
    user_token: Optional[str] = None,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """按用户 ID 或 Token 查询个人能量记忆，并按当前权益裁剪维度。"""
    try:
        access = combine_identity(member, user_id, user_token)
        if not access["known"]:
            raise ValueError("请提供 user_id 或 user_token")
        archive = list_readings(user_id=access["user_id"], user_token=access["user_token"])
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    tier = archive["user"]["membership_tier"]
    expires_at = archive["user"].get("expires_at")
    if tier not in HISTORY_TIERS:
        logger.info("history_locked user_id=%s tier=%s", archive["user"]["id"], tier)
        message = "状态复盘属于月度或年度能量守护，开通后可以回看每一次觉察。"
        if tier == TIER_FREE and subscription_expired(expires_at):
            message = "订阅已过期，状态复盘已关闭。重新开通月度或年度能量守护后可以回看每一次觉察。"
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
    request: CheckoutRequest,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """模拟支付：按 one_time、monthly、yearly 一键写入对应档位。"""
    try:
        access = combine_identity(member, request.user_id, request.user_token)
        if not access["known"]:
            raise UnknownUser("请先完成一次觉察，再开通方案")
        saved = apply_plan(
            request.plan_type,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info(
        "checkout_succeeded user_id=%s tier=%s plan_type=%s",
        saved["user_id"],
        saved["tier"],
        request.plan_type,
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
    request: DeepCreditRequest,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """模拟购买单次八字深度测算次数，不改变日常能量指引的会员档位。"""
    try:
        access = _known_access(member, request.user_id, request.user_token)
        saved = grant_deep_credits(
            quantity=request.quantity,
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
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
    request: DeepReportRequest,
    _: None = Depends(require_api_key),
    member: dict = Depends(identify_member),
):
    """八字深度测算。月卡年卡特权放行；否则扣减 1 次单次额度。"""
    try:
        access = _known_access(member, request.user_id, request.user_token)
        datetime.strptime(request.birth_date, "%Y-%m-%d")
        datetime.strptime(request.birth_time[:5], "%H:%M")
        resolve_birth_place(request.birth_city, request.longitude, request.latitude)
        normalize_zi_hour(request.zi_hour_mode)
        saved = authorize_deep_report(
            user_id=access.get("user_id"),
            user_token=access.get("user_token"),
        )
        report = compose_deep_report(
            request.birth_date,
            request.birth_time,
            request.gender,
            request.question,
            longitude=request.longitude,
            latitude=request.latitude,
            birth_city=request.birth_city,
            zi_hour_mode=request.zi_hour_mode,
        )
    except UnknownUser as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DeepReportLocked as exc:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "deep_report_locked",
                "message": "这次八字深度测算还没有打开。有效的月度或年度守护可以直接生成；否则需要至少 1 次单次测算额度。",
                "one_time_credits": exc.credits,
            },
        )
    except (ConflictingIdentity, InvalidMembership) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    logger.info(
        "deep_report_succeeded user_id=%s access_via=%s credits=%s birth_date=%s",
        saved["user_id"],
        saved["access_via"],
        saved["one_time_credits"],
        _redact_birth_date(request.birth_date),
    )
    return DeepReportResponse(
        status="success",
        product="deep_bazi",
        user_id=saved["user_id"],
        user_token=saved["user_token"],
        access_via=saved["access_via"],
        one_time_credits=saved["one_time_credits"],
        chart=BaziChartModel.model_validate(report["chart"]),
        chapters=[ReportChapter.model_validate(item) for item in report["chapters"]],
    )
