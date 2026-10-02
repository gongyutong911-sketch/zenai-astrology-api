import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="ZenAI Astrology API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class BaziRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    gender: str

@app.get("/")
def read_root():
    return {"status": "online"}

@app.post("/api/bazi/guidance")
def get_bazi_guidance(req: BaziRequest):
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="API Key is not configured on server.")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"用户公历出生日期：{req.year}年{req.month}月{req.day}日 {req.hour}时，性别：{req.gender}。请给出今日五行能量分析与行动建议。"
        response = model.generate_content(prompt)

        return {
            "success": True,
            "data": {
                "guidance": response.text
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini API error: {str(e)}")