import logging
import os
import secrets
import time
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from astrology_engine import get_astrology_energy_guidance

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class _HealthCheckAccessFilter(logging.Filter):
    """丢掉 GET / 的访问日志，避免 Render 存活探测刷屏。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return '"GET / ' not in record.getMessage()


def configure_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    for name in ("main", "astrology_engine"):
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


@app.get("/")
def read_root():
    return {"status": "ok", "message": "ZenAI Astrology & Energy API is running smoothly!"}


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

class EnergyGuidance(BaseModel):
    core_energy: str
    career_guidance: str
    relationship_advice: str


class EnergyResponse(BaseModel):
    status: str
    data: EnergyGuidance


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


@app.post("/api/energy-guidance", response_model=EnergyResponse)
def generate_energy_guidance(
    request: EnergyRequest,
    _: None = Depends(require_api_key),
):
    started = time.perf_counter()
    logger.info(
        "request_received birth_date=%s birth_time=%s gender=%s question=%s",
        _redact_birth_date(request.birth_date),
        _redact_birth_time(request.birth_time),
        request.gender,
        _redact_question(request.question),
    )
    try:
        # 调用 astrology_engine.py 中的核心计算与 AI 生成函数
        result = get_astrology_energy_guidance(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            gender=request.gender,
            question=request.question,
        )
        guidance = EnergyGuidance.model_validate(result)
    except Exception as exc:
        logger.exception(
            "request_failed status_code=500 elapsed_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        raise HTTPException(status_code=500, detail=str(exc))
    logger.info(
        "request_succeeded status_code=200 elapsed_ms=%.1f",
        (time.perf_counter() - started) * 1000,
    )
    return EnergyResponse(status="success", data=guidance)
