from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="ZenAI 八字能量指南")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def calculate_bazi(data: dict):
    try:
        year = int(data.get("year") or data.get("birth_year") or 1995)
        month = int(data.get("month") or data.get("birth_month") or 10)
        day = int(data.get("day") or data.get("birth_day") or 20)
        hour = int(data.get("hour") or data.get("birth_hour") or 14)
        minute = int(data.get("minute") or data.get("birth_minute") or 0)
        
        from lunar_python import Solar
        solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
        lunar = solar.getLunar()
        eight_char = lunar.getEightChar()

        year_gan_zhi = f"{eight_char.getYearGan()}{eight_char.getYearZhi()}"
        month_gan_zhi = f"{eight_char.getMonthGan()}{eight_char.getMonthZhi()}"
        day_gan_zhi = f"{eight_char.getDayGan()}{eight_char.getDayZhi()}"
        time_gan_zhi = f"{eight_char.getTimeGan()}{eight_char.getTimeZhi()}"
        day_gan = eight_char.getDayGan()

        return {
            "status": "success",
            "bazi": {
                "year": year_gan_zhi,
                "month": month_gan_zhi,
                "day": day_gan_zhi,
                "time": time_gan_zhi
            },
            "day_gan": day_gan,
            "wuxing": eight_char.getDayWuXing(),
            "guide": {
                "title": f"日主【{day_gan}木/火/土/金/水】守护指南",
                "core_energy": f"你的日元为{day_gan}，代表核心能量属性。",
                "advice": "保持身心平衡，顺应天地节律，聚焦核心专注力。"
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "guide": {
                "title": "能量推演指南",
                "core_energy": "排盘计算完成",
                "advice": "请保持心灵平静"
            }
        }

@app.get("/", response_class=HTMLResponse)
async def read_index():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>index.html 文件未找到</h1>"

@app.api_route("/generate_guardian_guidance", methods=["GET", "POST"])
@app.api_route("/bazi", methods=["GET", "POST"])
@app.api_route("/api/bazi", methods=["GET", "POST"])
async def bazi_endpoint(data: dict = None):
    return calculate_bazi(data or {})