import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

app = FastAPI(
    title="ZenAI Astrology & Energy API",
    description="基于八字与心理学的每日能量指导 API",
    version="1.0.0"
)

# 1. 配置 CORS 跨域中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. 从环境变量读取配置
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

if not api_key:
    raise ValueError("未检测到 OPENAI_API_KEY，请在 Render 后台 Environment 中配置。")

# 3. 初始化 OpenAI 客户端
client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    timeout=30.0,
    max_retries=3
)

# 4. 定义请求数据模型
class BaziRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    gender: str

# 5. 基础状态检查接口
@app.get("/")
def read_root():
    return {"status": "online", "message": "ZenAI Astrology API is working."}

# 6. 八字能量指导 API 接口
@app.post("/api/bazi/guidance")
def get_bazi_guidance(req: BaziRequest):
    try:
        user_prompt = f"用户公历出生日期：{req.year}年{req.month}月{req.day}日 {req.hour}时，性别：{req.gender}。请给出今日五行能量分析与行动建议。"

        response = client.chat.completions.create(
            model="gemini-1.5-flash",
            messages=[
                {
                    "role": "system",
                    "content": "你是一位精通中国传统八字命理与现代心理学、能量指导的专家。请提供温暖、客观、具建设性的每日能量指引。"
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0.7
        )

        guidance_text = response.choices[0].message.content
        return {
            "success": True,
            "data": {
                "guidance": guidance_text
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gemini API 调用异常: {str(e)}"
        )