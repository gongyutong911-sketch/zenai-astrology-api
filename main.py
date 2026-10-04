import os
import secrets
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from astrology_engine import get_astrology_energy_guidance

# 初始化 FastAPI 应用
app = FastAPI(
    title="ZenAI Astrology & Energy API",
    description="An AI-powered astrology and energy guidance API.",
    version="1.0.0"
)

@app.get("/")
def read_root():
    return {"status": "ok", "message": "ZenAI Astrology & Energy API is running smoothly!"}

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
        raise HTTPException(status_code=401, detail="未授权")


@app.post("/api/energy-guidance", response_model=EnergyResponse)
def generate_energy_guidance(
    request: EnergyRequest,
    _: None = Depends(require_api_key),
):
    try:
        # 调用 astrology_engine.py 中的核心计算与 AI 生成函数
        result = get_astrology_energy_guidance(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            gender=request.gender,
            question=request.question,
        )
        guidance = EnergyGuidance.model_validate(result)
        return EnergyResponse(status="success", data=guidance)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))