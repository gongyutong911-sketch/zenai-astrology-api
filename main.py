from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="ZenAI 八字能量指南")

# 开启 CORS 跨域支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入八字计算模块
try:
    from bazi import calculate_bazi
except Exception as e:
    def calculate_bazi(data):
        return {"error": f"Bazi module error: {str(e)}"}

# 1. 首页挂载 index.html
@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 文件未找到</h1>"

# 2. 匹配前端请求的接口路径 (同时支持 POST 和 GET，防止路径或请求方式匹配不上)
@app.api_route("/generate_guardian_guidance", methods=["GET", "POST"])
@app.api_route("/bazi", methods=["GET", "POST"])
@app.api_route("/api/bazi", methods=["GET", "POST"])
async def bazi_endpoint(data: dict = None):
    return calculate_bazi(data or {})