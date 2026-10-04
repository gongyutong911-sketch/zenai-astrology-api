import json
import os

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# 从环境变量中读取密钥和可选的自定义 Base URL（兼容标准 OpenAI 协议及中转网关）
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")  # 如果你有自定义的中转地址，会自动读取；没有则留空访问默认

# 初始化 OpenAI 客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url if base_url else None,
)

GUIDANCE_FIELDS = ("core_energy", "career_guidance", "relationship_advice")
# 网络抖动、超时、限流和服务端 5xx 才重试；参数错误不会因为重试而成功。
RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)


@retry(
    retry=retry_if_exception_type(RETRYABLE_ERRORS),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    stop=stop_after_attempt(3),  # 首次请求之外，最多再自动重试 2 次
    reraise=True,
)
def _create_guidance_completion(messages: list[dict]) -> str:
    """调用标准 Chat Completions，并在可恢复错误上按指数退避重试。"""
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "deepseek-flash"),
        messages=messages,
        temperature=0.7,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("模型未返回内容")
    return content


def _parse_guidance(content: str) -> dict[str, str]:
    """把 JSON Mode 的文本解析成固定字段，忽略模型多返回的其他键。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("模型返回的 JSON 不是对象")

    missing = [
        field
        for field in GUIDANCE_FIELDS
        if not isinstance(payload.get(field), str) or not payload[field].strip()
    ]
    if missing:
        raise ValueError(f"模型返回缺少字段: {', '.join(missing)}")

    return {field: payload[field].strip() for field in GUIDANCE_FIELDS}


def get_astrology_energy_guidance(
    birth_date: str,
    birth_time: str = "12:00",
    gender: str = "female",
    question: str = "今日能量指引",
) -> dict[str, str]:
    """
    核心能量命理计算与 AI 指引生成函数。
    返回包含 core_energy、career_guidance、relationship_advice 的结构化结果。
    """
    prompt = f"""
    你是一位专业的能量命理导师。请根据以下用户信息，只返回一个 JSON 对象，不要输出 Markdown 或额外说明。
    - 出生日期: {birth_date}
    - 出生时间: {birth_time}
    - 性别: {gender}
    - 咨询问题/主题: {question}

    JSON 必须包含且仅使用这三个字符串字段：
    - core_energy：核心能量，概括今日能量场与整体状态
    - career_guidance：事业指引，给出工作、学业或行动上的具体建议
    - relationship_advice：关系建议，给出人际与情感上的具体建议

    语言温暖、具体，每个字段都写成完整的一段话。
    """
    messages = [
        {
            "role": "system",
            "content": "你是一位专业的能量命理导师。请始终只输出合法 JSON 对象。",
        },
        {"role": "user", "content": prompt},
    ]
    return _parse_guidance(_create_guidance_completion(messages))
