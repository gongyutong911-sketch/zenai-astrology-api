import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# 加载本地 .env 环境变量
load_dotenv()

app = FastAPI(
    title="ZenAI Astrology & Energy API",
    description="基于中国传统八字与现代心理学的每日能量指导 API",
    version="1.0.0"
)

# ------------------------------------------------------------------
# 1. 配置 CORS 跨域中间件（解决 TypeError: Load failed / 跨域拦截问题）
# ------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 允许所有前端域名访问（生产环境可限定为指定域名）
    allow_credentials=True,     # 允许携带 Cookie / 认证头
    allow_methods=["*"],        # 允许所有 HTTP 方法 (GET, POST, OPTIONS 等)
    allow_headers=["*"],        # 允许所有请求头
)

# ------------------------------------------------------------------
# 2. 初始化 OpenAI 客户端（兼容 Gemini API Endpoint）
# ------------------------------------------------------------------
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

if not api_key:
    raise ValueError("未检测到 OPENAI_API_KEY 环境变量，请在 Render 或 .env 中进行配置。")

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

# ------------------------------------------------------------------
# 3. 定义请求参数模型 (Pydantic Schema)
# ------------------------------------------------------------------
class BaziRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    gender: str  # "male" 或 "female"

# ------------------------------------------------------------------
# 4. API 路由定义
# ------------------------------------------------------------------
@app.get("/")
def read_root():
    return {"status": "online", "message": "ZenAI Astrology API is running smoothly."}

@app.post("/api/bazi/guidance")
def get_bazi_guidance(req: BaziRequest):
    try:
        # TODO: 替换为你的八字计算逻辑/Prompt 组装
        # 这里模拟提取到的八字与系统 Prompt
        prompt = f"用户公历出生日期：{req.year}年{req.month}月{req.day}日 {req.hour}时，性别：{req.gender}。请给出今日五行能量与行动建议。"

        response = client.chat.completions.create(
            model="gemini-1.5-flash",  # 或 "gemini-1.5-pro" / "gpt-3.5-turbo"
            messages=[
                {"role": "system", "content": "你是一位精通中国传统八字命理与现代心理学、能量指导的专家。请提供温暖、客观、具建设性的每日能量指引。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        guidance_text = response.choices[0].message.content
        return {"success": True, "guidance": guidance_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))