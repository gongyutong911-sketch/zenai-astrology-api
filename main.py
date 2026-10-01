import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from lunar_python import Lunar
from openai import OpenAI

app = FastAPI(title="ZENAI Astrology API")

# 初始化 OpenAI 客户端（自动读取环境变量中的 OPENAI_API_KEY）
client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),
    base_url=os.environ.get("OPENAI_BASE_URL")  # 如果使用 DeepSeek 等兼容服务可配置此环境变量
)

# 1. 根路由：直接返回 index.html 前端页面
@app.get("/")
async def read_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "index.html not found"}

# 请求体数据结构
class BaziRequest(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    gender: str = "male"

# 2. 八字与运势生成接口
@app.post("/api/bazi/guidance")
async def generate_guidance(req: BaziRequest):
    try:
        # 使用 lunar-python 进行阴历与八字排盘
        lunar = Lunar.fromYmdHms(req.year, req.month, req.day, req.hour, 0, 0)
        eight_char = lunar.getEightChar()
        
        bazi_str = f"{eight_char.getYear()}年 {eight_char.getMonth()}月 {eight_char.getDay()}日 {eight_char.getTime()}时"
        gender_str = "乾造 (男)" if req.gender == "male" else "坤造 (女)"

        prompt = f"""
你是一位深谙东方哲理与八字能量的禅意导师。
请根据以下生辰八字排盘信息，为用户生成一份充满启发性、温暖且极具深度的八字能量守护指南。

【排盘信息】
- 生辰八字：{bazi_str}
- 性别：{gender_str}

【生成要求】
1. 使用 Markdown 格式输出，包含清晰的标题（##）、重点加粗与段落排版。
2. 内容包含三个核心板块：
   - ## 1. 命盘五行能量特质
   - ## 2. 当前阶段机缘与挑战
   - ## 3. ZENAI 专属能量守护建议
3. 字数要求在 600 - 1000 字左右，语气客观、禅意且富有正能量。
"""

        # 调用 LLM 生成运势（已修正语法结构）
        response = client.chat.completions.create(
            model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "你是一位专业的东方智慧与八字运势解读导师。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )

        guidance_content = response.choices[0].message.content

        return {
            "success": True,
            "bazi": bazi_str,
            "guidance": guidance_content
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))