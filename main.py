from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os

# 导入你的八字计算逻辑
from bazi import calculate_bazi

app = FastAPI(title="ZenAI 八字能量指南")

# 1. 根路径挂载：访问首页 / 时返回 index.html
@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 文件未找到</h1>"

# 2. 八字计算 API 接口
@app.post("/api/bazi")
async def bazi_endpoint(data: dict):
    result = calculate_bazi(data)
    return result