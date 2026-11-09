import json
import logging
import os
import time
from typing import Optional

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Instant 履约只使用这一组变量，不回退到 OPENAI_ADMIN_KEY 或其他 Bot 密钥。
INSTANT_API_KEY_ENV = "OPENAI_API_KEY"
INSTANT_BASE_URL_ENV = "OPENAI_BASE_URL"
INSTANT_MODEL_ENV = "OPENAI_MODEL"
DEFAULT_MODEL = "deepseek-flash"

_client = None
_client_signature = None


class GuidanceRateLimited(Exception):
    """上游限流。不再自动重试，避免把 Instant 配额打穿。"""

    def __init__(self, retry_after: Optional[float] = None):
        super().__init__("rate_limited")
        self.retry_after = retry_after


class GuidanceUnavailable(Exception):
    """连接、超时或上游 5xx 在有限次重试后仍失败。"""

    def __init__(self, reason: str = "unavailable"):
        super().__init__(reason)
        self.reason = reason


class GuidanceOutputError(ValueError):
    """模型返回空内容或无法解析的 JSON。"""

GUIDANCE_FIELDS = (
    "core_energy",
    "career_guidance",
    "relationship_advice",
    "wealth_flow",
    "action_tips",
    "lucky_elements",
)
FREE_FIELDS = ("core_energy", "career_guidance", "relationship_advice")
DAILY_SIGN_FIELDS = FREE_FIELDS
DEPTH_DAILY = "foundation"
DEPTH_COACHING = "full_coaching"
# 网络抖动、超时和服务端 5xx 才重试。429 会继续消耗 Instant 配额，所以不重试。
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError, GuidanceOutputError)


def _log_retry(retry_state) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    wait_s = retry_state.next_action.sleep if retry_state.next_action else 0
    logger.warning(
        "model_call_retry attempt=%s wait_s=%.1f error=%s",
        retry_state.attempt_number,
        wait_s,
        type(exc).__name__ if exc else "unknown",
    )


def _reset_client_cache() -> None:
    global _client, _client_signature
    _client = None
    _client_signature = None


def _instant_credentials() -> tuple:
    """只读取 Instant 履约自己的密钥和网关，忽略管理密钥与其他 Bot 密钥。"""
    api_key = os.getenv(INSTANT_API_KEY_ENV, "").strip()
    base_url = os.getenv(INSTANT_BASE_URL_ENV, "").strip() or None
    return api_key, base_url


def _openai_client() -> OpenAI:
    global _client, _client_signature
    api_key, base_url = _instant_credentials()
    signature = (api_key, base_url)
    if _client is not None and _client_signature == signature:
        return _client
    if not api_key:
        raise GuidanceUnavailable("missing_api_key")
    # max_retries=0：官方 SDK 默认会重试 429。限流交给上面的分类，不在客户端里再打两次。
    # admin_api_key 显式置空，避免 OPENAI_ADMIN_KEY 被当成这只客户端的凭证。
    kwargs = {"api_key": api_key, "admin_api_key": "", "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    _client = OpenAI(**kwargs)
    _client_signature = signature
    return _client


def _retry_after_seconds(exc) -> Optional[float]:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        raw = headers.get("retry-after")
    except Exception:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0 or seconds > 120:
        return None
    return seconds


@retry(
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),  # 首次请求之外，最多再自动重试 2 次
    before_sleep=_log_retry,
    reraise=True,
)
def _complete_guidance(messages: list[dict], fields: tuple) -> dict:
    """调用标准 Chat Completions。空响应和坏 JSON 会再试，限流不会。"""
    model = os.getenv(INSTANT_MODEL_ENV, DEFAULT_MODEL)
    started = time.perf_counter()
    logger.info("model_request_start model=%s", model)
    try:
        response = _openai_client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
    except RateLimitError as exc:
        logger.warning(
            "model_request_rate_limited model=%s elapsed_ms=%.1f",
            model,
            (time.perf_counter() - started) * 1000,
        )
        raise GuidanceRateLimited(_retry_after_seconds(exc)) from None
    except RETRYABLE_ERRORS as exc:
        logger.warning(
            "model_request_failed model=%s elapsed_ms=%.1f error=%s",
            model,
            (time.perf_counter() - started) * 1000,
            type(exc).__name__,
        )
        raise
    except Exception as exc:
        logger.warning(
            "model_request_failed model=%s elapsed_ms=%.1f error=%s",
            model,
            (time.perf_counter() - started) * 1000,
            type(exc).__name__,
        )
        raise GuidanceUnavailable(type(exc).__name__) from None
    choices = getattr(response, "choices", None) or []
    content = None
    if choices and getattr(choices[0], "message", None) is not None:
        content = choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise GuidanceOutputError("模型未返回内容")
    try:
        guidance = _parse_guidance(content, fields)
    except GuidanceOutputError:
        raise
    except ValueError as exc:
        raise GuidanceOutputError(str(exc)) from exc
    logger.info(
        "model_request_done model=%s elapsed_ms=%.1f",
        model,
        (time.perf_counter() - started) * 1000,
    )
    return guidance


def _parse_guidance(content: str, fields: tuple = GUIDANCE_FIELDS) -> dict[str, str]:
    """把 JSON Mode 的文本解析成指定字段，忽略模型多返回的其他键。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GuidanceOutputError("模型返回的 JSON 无法解析") from exc
    if not isinstance(payload, dict):
        raise GuidanceOutputError("模型返回的 JSON 不是对象")

    missing = [
        field
        for field in fields
        if not isinstance(payload.get(field), str) or not payload[field].strip()
    ]
    if missing:
        raise GuidanceOutputError(f"模型返回缺少字段: {', '.join(missing)}")

    return {field: payload[field].strip() for field in fields}


_COACH_SYSTEM = """你是一位现代心理能量教练。你帮助用户觉察当下的内在消耗、情绪节奏和思维盲点，并把觉察翻译成温和、可执行的成长指引。
写作时要让人感到被准确看见：点出此刻可能正在发生的内耗、自我拉扯，以及一个还没被说破的认知盲点，然后给出一个可以马上用上的温柔转向。
遵守这些边界：
- 只用可能性语言，例如“也许”“倾向于”“可以试试”。不要使用“一定”“必然”“注定”“躲不过”等绝对化断言。
- 不要使用封建迷信、吉凶祸福、鬼神、改命、开运、破财、血光等说法，也不要用恐吓或稀缺来制造焦虑。
- 出生日期和时间只作为理解生活节奏的背景，不要推算命运，不要预测吉凶。
- 只输出合法 JSON 对象，不要 Markdown，不要额外说明。"""


def _guidance_messages(
    birth_date: str,
    birth_time: str,
    gender: str,
    question: str,
    depth: str,
) -> list:
    profile = f"""
    - 出生日期: {birth_date}
    - 出生时间: {birth_time}
    - 性别: {gender}
    - 想觉察的问题: {question}
    """
    if depth == DEPTH_DAILY:
        prompt = f"""
    请根据以下背景，做一次能量状态诊断与认知盲点扫描。只返回一个 JSON 对象。
    这是免费层的前三个维度，请写得具体、有穿透力，让人第一次阅读就觉得被理解，同时保持温和和专业。
    {profile}
    JSON 必须包含且仅使用这三个字符串字段：
    - core_energy：核心能量。描述今天的能量状态、情绪底色，以及最耗神的那一种内在拉扯。
    - career_guidance：事业觉察。针对工作、学业或创作，指出一个思维盲点，以及今天更适合推进和适合暂缓的事。
    - relationship_advice：关系觉察。针对亲密关系、合作与沟通，指出一个容易忽略的互动模式，并给出一个更轻松的说法。

    每个字段写成完整的一段话。不要写财富行动、破局步骤或每日注意力锚点。
    """
        system = _COACH_SYSTEM + "\n这一次只输出核心能量、事业觉察和关系觉察三个字段。"
    elif depth == DEPTH_COACHING:
        prompt = f"""
    请根据以下背景，完成能量状态诊断，并补上 Pro 进阶版行动方案。只返回一个 JSON 对象。
    前三个维度负责看见内耗和盲点；后三个维度负责把看见变成今天可以做的一小步。
    {profile}
    JSON 必须包含且仅使用这六个字符串字段：
    - core_energy：核心能量。描述今天的能量状态、情绪底色，以及最耗神的那一种内在拉扯。
    - career_guidance：事业觉察。针对工作、学业或创作，指出一个思维盲点，以及今天更适合推进和适合暂缓的事。
    - relationship_advice：关系觉察。针对亲密关系、合作与沟通，指出一个容易忽略的互动模式，并给出一个更轻松的说法。
    - wealth_flow：财富行动。从注意力、边界和资源分配来看今天的收支与合作，说明哪里可以更从容，哪里适合先观察。不要预言财运。
    - action_tips：破局锦囊。给出 2 到 3 个今天就能完成的小行动，按先后顺序写成一段话，帮助用户从内耗里走出来。
    - lucky_elements：每日幸运指引。给一个颜色、一个数字、一个方位，再加一个一分钟内能做的身心小仪式，作为今天的注意力锚点。把它说成提醒，不要说成改运。

    语言温暖、具体、专业。每个字段都写成完整的一段话，不要使用列表符号。
    """
        system = _COACH_SYSTEM + "\n这一次输出全部六个字段，后三个是 Pro 进阶版行动方案。"
    else:
        raise ValueError(f"不支持的解读深度: {depth}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def get_astrology_energy_guidance(
    birth_date: str,
    birth_time: str = "12:00",
    gender: str = "female",
    question: str = "今日能量指引",
    depth: str = DEPTH_COACHING,
) -> dict[str, str]:
    """
    心理能量教练的结构化觉察。
    depth 为 foundation 时生成前三个诊断维度；full_coaching 时一并生成 Pro 进阶版行动方案。
    """
    fields = FREE_FIELDS if depth == DEPTH_DAILY else GUIDANCE_FIELDS
    messages = _guidance_messages(birth_date, birth_time, gender, question, depth)
    started = time.perf_counter()
    try:
        guidance = _complete_guidance(messages, fields)
    except GuidanceRateLimited:
        logger.warning(
            "model_call_rate_limited elapsed_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        raise
    except GuidanceOutputError:
        logger.warning(
            "model_call_unusable elapsed_ms=%.1f",
            (time.perf_counter() - started) * 1000,
        )
        raise
    except GuidanceUnavailable as exc:
        logger.warning(
            "model_call_unavailable elapsed_ms=%.1f error=%s",
            (time.perf_counter() - started) * 1000,
            exc.reason,
        )
        raise
    except Exception as exc:
        logger.error(
            "model_call_exhausted elapsed_ms=%.1f error=%s",
            (time.perf_counter() - started) * 1000,
            type(exc).__name__,
        )
        raise
    logger.info(
        "model_call_succeeded elapsed_ms=%.1f",
        (time.perf_counter() - started) * 1000,
    )
    return guidance
