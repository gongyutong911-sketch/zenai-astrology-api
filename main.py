import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from lunar_python import Solar
from openai import AsyncOpenAI

app = FastAPI(title="ZENAI 八字能量 API")

# 1. 初始化 AI 客户端
# 默认读取环境变量中的 OPENAI_API_KEY
client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "your-api-key-here"),
    # 如果使用 DeepSeek，取消下面这行注释并填入 base_url：
    # base_url="https://api.deepseek.com/v1"
)

# 2. 定义请求格式
class BaziRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    gender: str = "male"

# 3. 辅助函数：计算四柱干支
def calculate_bazi_data(year: int, month: int, day: int, hour: int):
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    lunar = solar.getLunar()
    ba_zi = lunar.getEightChar()
    
    return {
        "year": ba_zi.getYear(),
        "month": ba_zi.getMonth(),
        "day": ba_zi.getDay(),
        "time": ba_zi.getTime(),
        "day_gan": ba_zi.getDayGan(),
        "wuxing": f"日主天干为【{ba_zi.getDayGan()}】"
    }

# 4. 核心 API：调用大模型生成深度解读
@app.post("/generate_guardian_guidance")
async def generate_guardian_guidance(req: BaziRequest):
    try:
        bazi = calculate_bazi_data(req.year, req.month, req.day, req.hour)
        gender_str = "乾造（男）" if req.gender == "male" else "坤造（女）"

        prompt = f"""
你是一位精通子平八字与五行能量学的资深命理导师。
请根据以下盘块信息，为用户撰写一份 1000 字左右的【八字与五行能量深度守护指南】。

【生辰排盘信息】
- 性别：{gender_str}
- 年柱：{bazi['year']}
- 月柱：{bazi['month']}
- 日柱：{bazi['day']} （日主为：{bazi['day_gan']}）
- 时柱：{bazi['time']}

【内容与结构要求】
1. **日主本命性格与能量格局**（约 300 字）：分析日主天干的五行特质、性格优势与潜在盲点。
2. **五行喜忌与能量平衡**（约 300 字）：结合四柱整体，分析五行的强弱分布，指出需要补充或疏导的能量。
3. **事业与财富能量指南**（约 200 字）：给予实际的职场定位建议与财富守护法则。
4. **身心调频与生活建议**（约 200 字）：包含适合的幸运色彩、方位、饮食或日常冥想习惯。

要求：使用 Markdown 语法排版，语言风格深邃、温和且具有穿透力，避免封建迷信色彩，侧重于心理赋能与现代生活指导。
"""

        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # 若改用 DeepSeek，可填 "deepseek-chat"
            messages=[
                {"role": "system", "content": "你是一位专业的东方能量学与八字命理分析大师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2500
        )

        ai_analysis = response.choices[0].message.content

        return {
            "bazi": bazi,
            "day_gan": bazi['day_gan'],
            "wuxing": bazi['wuxing'],
            "guide": {
                "title": f"日主【{bazi['day_gan']}】能量深度守护指南",
                "core_energy": f"四柱干支：{bazi['year']} | {bazi['month']} | {bazi['day']} | {bazi['time']}",
                "advice": ai_analysis
            }
        }

    except Exception as e:
        print(f"AI 调用异常: {e}")
        bazi = calculate_bazi_data(req.year, req.month, req.day, req.hour)
        return {
            "bazi": bazi,
            "day_gan": bazi['day_gan'],
            "wuxing": bazi['wuxing'],
            "guide": {
                "title": f"日主【{bazi['day_gan']}】能量守护指南",
                "core_energy": f"四柱干支：{bazi['year']} | {bazi['month']} | {bazi['day']} | {bazi['time']}",
                "advice": "保持身心平衡，凝聚专注力，顺应天地自然节律。（注：当前未配置有效的 API Key，这是默认提示）"
            }
        }