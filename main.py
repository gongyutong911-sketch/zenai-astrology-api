from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="ZenAI 八字能量指南")

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def calculate_bazi(data: dict):
    try:
        # 容错提取前端参数
        year = int(data.get("year") or data.get("birth_year") or 1995)
        month = int(data.get("month") or data.get("birth_month") or 10)
        day = int(data.get("day") or data.get("birth_day") or 20)
        hour = int(data.get("hour") or data.get("birth_hour") or 14)
        minute = int(data.get("minute") or data.get("birth_minute") or 0)
        
        # 调用 lunar_python 进行公历转八字
        from lunar_python import Solar
        solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
        lunar = solar.getLunar()
        eight_char = lunar.getEightChar()

        return {
            "status": "success",
            "bazi": {
                "year": eight_char.getYear(),
                "month": eight_char.getMonth(),
                "day": eight_char.getDay(),
                "time": eight_char.getTime()
            },
            "day_gan": eight_char.getDayGan(),
            "wuxing": eight_char.getDayWuXing()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

# 1. 首页挂载 index.html
@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 文件未找到</h1>"

# 2. 兼容各种接口路径与请求方式
@app.api_route("/generate_guardian_guidance", methods=["GET", "POST"])
@app.api_route("/bazi", methods=["GET", "POST"])
@app.api_route("/api/bazi", methods=["GET", "POST"])
async def bazi_endpoint(data: dict = None):
    return calculate_bazi(data or {})