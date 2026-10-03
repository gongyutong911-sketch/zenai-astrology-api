import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
from astrology_engine import get_astrology_energy_guidance  # 确保导入你的核心引擎模块

# 初始化 FastAPI 应用
app = FastAPI(
    title="ZenAI Astrology & Energy API",
    description="An AI-powered astrology and energy guidance API using Google Gemini.",
    version="1.0.0"
)

# 配置 Gemini API 密钥（优先从环境变量读取）
GEMINI_API_KEY = os.getenv("OPENAI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 定义请求体数据结构
class EnergyRequest(BaseModel):
    birth_date: str
    birth_time: str = "12:00"
    gender: str = "female"
    question: str = "今日能量指引"

@app.get("/")
def read_root():
    return {"status": "ok", "message": "ZenAI Astrology & Energy API is running smoothly!"}

@app.post("/api/energy-guidance")
def generate_energy_guidance(request: EnergyRequest):
    try:
        # 调用 astrology_engine.py 中的核心计算与 AI 生成函数
        result = get_astrology_energy_guidance(
            birth_date=request.birth_date,
            birth_time=request.birth_time,
            gender=request.gender,
            question=request.question
        )
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))