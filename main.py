from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import os

app = FastAPI(title="ZenAI 八字能量指南")

# 尝试导入八字计算逻辑
try:
    from bazi import calculate_bazi
except Exception as e:
    def calculate_bazi(data):
        return {"error": f"Bazi calculation module error: {str(e)}"}

# 1. 首页挂载 index.html
@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 文件未找到</h1>"
