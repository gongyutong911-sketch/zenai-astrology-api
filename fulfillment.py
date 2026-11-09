"""Instant 履约的校验、限流、幂等和可对外返回的错误文案。

模型调用仍只走 astrology_engine 里的 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL。
这里不读取、也不回退到任何 Bot 密钥。
"""

import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import bazi

logger = logging.getLogger("fulfillment")

QUESTION_MAX = 2000
GENDER_MAX = 16
CITY_MAX = 32
IDEMPOTENCY_MIN = 16
IDEMPOTENCY_MAX = 128
RATE_WINDOW_SECONDS = 60.0

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
_LOCALE_TAG = re.compile(r"^[a-z]{1,8}(?:-[a-z0-9]{1,8})*$")
_SCRUBBERS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-+/=]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password|authorization)\s*[=:]\s*\S+"),
)

# 这些中文句子已经出现在现有接口里。默认语言保持原文，英文只在 Accept-Language 明确要 en 时使用。
COPY = {
    "unauthorized": {"zh": "未授权", "en": "Unauthorized"},
    "rate_limited": {
        "zh": "请求过于频繁，请稍后再试",
        "en": "Too many requests. Please retry shortly.",
    },
    "model_rate_limited": {
        "zh": "能量指引暂时排队，请稍后再试",
        "en": "Guidance is temporarily queued. Please retry shortly.",
    },
    "model_unavailable": {
        "zh": "能量指引暂时无法完成，请稍后再试",
        "en": "Guidance is temporarily unavailable. Please retry.",
    },
    "model_output": {
        "zh": "能量指引没有生成完整内容，请再试一次",
        "en": "Guidance came back incomplete. Please retry.",
    },
    "internal": {
        "zh": "能量指引暂时无法完成，请稍后再试",
        "en": "Guidance is temporarily unavailable. Please retry.",
    },
    "idempotency_conflict": {
        "zh": "幂等键与请求内容不一致",
        "en": "Idempotency key was reused with a different request.",
    },
    "idempotency_in_progress": {
        "zh": "相同请求正在处理，请稍后再试",
        "en": "The same request is still being processed.",
    },
    "birth_date": {
        "zh": "出生日期需要是 YYYY-MM-DD",
        "en": "Birth date must be YYYY-MM-DD.",
    },
    "birth_time": {
        "zh": "出生时间需要是 HH:MM",
        "en": "Birth time must be HH:MM.",
    },
    "gender": {"zh": "性别无法读取", "en": "Gender could not be read."},
    "question": {"zh": "问题过长", "en": "Question is too long."},
    "birth_city": {"zh": "出生城市无法读取", "en": "Birth city could not be read."},
    "idempotency_key": {
        "zh": "幂等键格式不正确",
        "en": "Idempotency key format is invalid.",
    },
    "history_locked": {
        "zh": "状态复盘属于月度或年度能量守护，开通后可以回看每一次觉察。",
        "en": "History belongs to the monthly or yearly plan.",
    },
    "history_expired": {
        "zh": "订阅已过期，状态复盘已关闭。重新开通月度或年度能量守护后可以回看每一次觉察。",
        "en": "The subscription has expired, so history is closed.",
    },
    "deep_locked": {
        "zh": "这次八字深度测算还没有打开。有效的月度或年度守护可以直接生成；否则需要至少 1 次单次测算额度。",
        "en": "This deep reading is locked. An active monthly or yearly plan can open it; otherwise at least one credit is required.",
    },
}

EN_MESSAGES = {
    "未找到对应用户": "User was not found.",
    "用户标识不一致": "User identity does not match.",
    "不支持的会员等级": "Unsupported membership tier.",
    "不支持的订阅方案": "Unsupported plan.",
    "购买次数需要在 1 到 99 之间": "Quantity must be between 1 and 99.",
    "请提供 user_id 或 user_token": "Provide user_id or user_token.",
    "请先完成一次觉察，再开通方案": "Complete one reading before opening a plan.",
    "请先完成一次觉察，再使用深度测算": "Complete one reading before a deep report.",
    "出生城市无法对应经度，请改填经度": "Birth city has no known longitude. Provide a longitude.",
    "经度或纬度无法读取": "Longitude or latitude could not be read.",
    "经度需在 -180 到 180 之间": "Longitude must be between -180 and 180.",
    "纬度需在 -90 到 90 之间": "Latitude must be between -90 and 90.",
    "子时划分只能是早子时或晚子时": "Zi-hour mode must be early or late.",
    "出生日期或时间无法排盘": "Birth date or time could not be charted.",
    "节气时刻无法确定": "Solar term time could not be determined.",
    "排盘结果不完整": "The chart came back incomplete.",
    "深度测算尚未开通": "This deep reading is locked.",
}


class InputRejected(ValueError):
    """调用方可以改正的履约参数。code 对应 COPY。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RateLimited(Exception):
    """本进程内的入口限流，在调用模型之前拦住。"""

    def __init__(self, retry_after: float):
        super().__init__("rate_limited")
        self.retry_after = max(1, min(120, int(retry_after + 0.999)))


@dataclass(frozen=True)
class EnergyInput:
    birth_date: str
    birth_time: str
    gender: str
    question: str


@dataclass(frozen=True)
class DeepInput:
    birth_date: str
    birth_time: str
    gender: str
    question: str
    birth_city: Optional[str]
    longitude: Optional[float]
    latitude: Optional[float]
    zi_hour_mode: str


class _WindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def hit(self, bucket: str, limit: int, now: float, window: float = RATE_WINDOW_SECONDS) -> Optional[float]:
        if limit <= 0:
            return None
        with self._lock:
            events = [stamp for stamp in self._events.get(bucket, []) if now - stamp < window]
            if len(events) >= limit:
                self._events[bucket] = events
                return max(0.1, window - (now - events[0]))
            events.append(now)
            self._events[bucket] = events
            return None


LIMITER = _WindowLimiter()


def reset_rate_limiter() -> None:
    LIMITER.reset()


def rate_limit_per_minute() -> int:
    raw = os.getenv("INSTANT_RATE_LIMIT_PER_MINUTE", "30").strip()
    try:
        value = int(raw)
    except ValueError:
        return 30
    return max(0, min(value, 1000))


def enforce_rate_limit(bucket: str) -> None:
    retry_after = LIMITER.hit(bucket, rate_limit_per_minute(), time.monotonic())
    if retry_after is not None:
        raise RateLimited(retry_after)


def negotiate_locale(header: Optional[str]) -> str:
    """只认 zh / en。坏掉的 Accept-Language 回落到中文，不让解析错误变成 500。"""
    if not header:
        return "zh"
    ranked = []
    for item in header[:200].split(","):
        item = item.strip()
        if not item:
            continue
        bits = item.split(";", 1)
        tag = bits[0].strip().lower()
        quality = 1.0
        if len(bits) == 2:
            match = re.match(r"q\s*=\s*([0-9]*\.?[0-9]+)", bits[1].strip(), re.IGNORECASE)
            if match is None:
                continue
            try:
                quality = float(match.group(1))
            except ValueError:
                continue
            if quality <= 0 or quality > 1:
                continue
        if tag != "*" and _LOCALE_TAG.fullmatch(tag) is None:
            continue
        ranked.append((quality, tag))
    ranked.sort(key=lambda item: item[0], reverse=True)
    for _, tag in ranked:
        if tag == "*" or tag.startswith("zh"):
            return "zh"
        if tag.startswith("en"):
            return "en"
    return "zh"


def copy_text(locale: str, code: str) -> str:
    row = COPY[code]
    if locale == "en":
        return row["en"]
    return row["zh"]


def localize(locale: str, message: str) -> str:
    if locale == "en":
        return EN_MESSAGES.get(message, message)
    return message


def scrub(value: str) -> str:
    text = value.replace("\r", " ").replace("\n", " ")
    for pattern in _SCRUBBERS:
        text = pattern.sub("[redacted]", text)
    return text[:500]


def log_event(level: int, event: str, **fields) -> None:
    """键值日志。身份密钥、口令和换行不会进入日志。"""
    banned = {
        "token",
        "user_token",
        "api_key",
        "authorization",
        "secret",
        "password",
        "x_api_key",
        "idempotency_key",
    }
    parts = [event]
    for key in sorted(fields):
        if key.lower() in banned:
            continue
        value = fields[key]
        if isinstance(value, str):
            value = scrub(value)
        parts.append(f"{key}={value}")
    logger.log(level, " ".join(parts))


def redact_birth_date(value: str) -> str:
    parts = (value or "").strip().split("-")
    if len(parts) == 3 and len(parts[0]) == 4 and parts[0].isdigit():
        return f"{parts[0]}-{parts[1]}-**"
    return "****"


def redact_birth_time(value: str) -> str:
    hour, _, _minute = (value or "").strip().partition(":")
    if hour.isdigit():
        return f"{int(hour):02d}:**"
    return "**:**"


def redact_question(value: str) -> str:
    text = scrub(" ".join((value or "").split()))
    if not text:
        return ""
    preview = text[:8] + ("..." if len(text) > 8 else "")
    return f"{preview} (len={len(text)})"


def _strip_controls(value: str) -> str:
    return "".join(ch for ch in value if ord(ch) >= 32)


def parse_birth_date(value: Optional[str]) -> str:
    text = _strip_controls(value or "").strip()
    parts = text.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or not all(part.isdigit() for part in parts):
        raise InputRejected("birth_date")
    year, month, day = (int(part) for part in parts)
    try:
        parsed = datetime(year, month, day)
    except ValueError:
        raise InputRejected("birth_date")
    if not 1900 <= parsed.year <= 2100:
        raise InputRejected("birth_date")
    return parsed.strftime("%Y-%m-%d")


def parse_birth_time(value: Optional[str]) -> str:
    text = _strip_controls(value or "").strip()
    parts = text.split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        raise InputRejected("birth_time")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise InputRejected("birth_time")
    if second is not None and not 0 <= second <= 59:
        raise InputRejected("birth_time")
    if second is None:
        return f"{hour:02d}:{minute:02d}"
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def parse_gender(value: Optional[str]) -> str:
    text = _strip_controls(value or "").strip()
    if not text or len(text) > GENDER_MAX:
        raise InputRejected("gender")
    return text


def parse_question(value: Optional[str], default: str) -> str:
    text = " ".join(_strip_controls(value or "").split())
    if not text:
        return default
    if len(text) > QUESTION_MAX:
        raise InputRejected("question")
    return text


def parse_city(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = _strip_controls(value).strip()
    if not text:
        return None
    if len(text) > CITY_MAX:
        raise InputRejected("birth_city")
    return text


def parse_idempotency_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > IDEMPOTENCY_MAX or _IDEMPOTENCY_KEY.fullmatch(text) is None:
        raise InputRejected("idempotency_key")
    return text


def normalize_energy(birth_date: str, birth_time: str, gender: str, question: str) -> EnergyInput:
    return EnergyInput(
        birth_date=parse_birth_date(birth_date),
        birth_time=parse_birth_time(birth_time),
        gender=parse_gender(gender),
        question=parse_question(question, "今日能量指引"),
    )


def normalize_deep(
    birth_date: str,
    birth_time: str,
    gender: str,
    question: str,
    birth_city: Optional[str],
    longitude: Optional[float],
    latitude: Optional[float],
    zi_hour_mode: str,
) -> DeepInput:
    return DeepInput(
        birth_date=parse_birth_date(birth_date),
        birth_time=parse_birth_time(birth_time),
        gender=parse_gender(gender),
        question=parse_question(question, "想看清此刻的处境"),
        birth_city=parse_city(birth_city),
        longitude=longitude,
        latitude=latitude,
        zi_hour_mode=bazi.normalize_zi_hour(zi_hour_mode),
    )


def fingerprint(payload: dict) -> str:
    import json

    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def idempotency_scope(
    route: str,
    *,
    user_id: Optional[int],
    user_token: Optional[str],
    idempotency_key: str,
) -> str:
    """已知用户按档案隔离。匿名请求把幂等键本身当作能力凭证，避免共享 API Key 串读。"""
    if user_id is not None:
        who = f"user:{user_id}"
    elif user_token:
        who = "token:" + _digest(user_token)
    else:
        who = "anon:" + _digest(idempotency_key, 24)
    return f"{route}:{who}"[:160]


def rate_bucket(
    *,
    user_id: Optional[int],
    user_token: Optional[str],
    api_key: Optional[str],
    host: Optional[str],
) -> str:
    if user_id is not None:
        return f"user:{user_id}"
    if user_token:
        return "token:" + _digest(user_token)
    if api_key:
        return "key:" + _digest(api_key)
    return "host:" + (host or "unknown")


def key_hint(idempotency_key: str) -> str:
    return _digest(idempotency_key, 8)


def guidance_is_usable(guidance: dict, fields: tuple) -> bool:
    return all(isinstance(guidance.get(field), str) and guidance[field].strip() for field in fields)
