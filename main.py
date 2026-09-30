import os
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from lunar_python import Solar
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="ZenAI Astrology & Energy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

GAN_WU_XING = {
    "甲": "Wood", "乙": "Wood", "丙": "Fire", "丁": "Fire", "戊": "Earth",
    "己": "Earth", "庚": "Metal", "辛": "Metal", "壬": "Water", "癸": "Water",
}
GAN_YIN_YANG = {
    "甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
    "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0,
}
WU_XING_SHENG = {"Wood": "Fire", "Fire": "Earth", "Earth": "Metal", "Metal": "Water", "Water": "Wood"}
WU_XING_KE = {"Wood": "Earth", "Earth": "Water", "Water": "Fire", "Fire": "Metal", "Metal": "Wood"}
WU_XING_CN = {"Wood": "木", "Fire": "火", "Earth": "土", "Metal": "金", "Water": "水"}

SHI_SHEN_EN = {
    "比肩": "Peer Energy (Friend)",
    "劫财": "Competitive Energy (Competitor)",
    "食神": "Creative Flow (Artist)",
    "伤官": "Expressive Power (Rebel)",
    "偏财": "Opportunity Attraction (Pioneer)",
    "正财": "Stable Fortune (Builder)",
    "七杀": "Drive & Authority (Warrior)",
    "正官": "Structure & Leadership (Officer)",
    "偏印": "Intuition & Wisdom (Philosopher)",
    "正印": "Nurturing Mind (Mentor)",
    "日主": "Day Master (Self)",
}

GAN_CN_TO_EN = {
    "甲": "Jia (Yang Wood)", "乙": "Yi (Yin Wood)",
    "丙": "Bing (Yang Fire)", "丁": "Ding (Yin Fire)",
    "戊": "Wu (Yang Earth)", "己": "Ji (Yin Earth)",
    "庚": "Geng (Yang Metal)", "辛": "Xin (Yin Metal)",
    "壬": "Ren (Yang Water)", "癸": "Gui (Yin Water)",
}

DAY_MASTER_GUIDANCE = {
    "甲": {
        "title": "参天甲木 · 破土生长",
        "essence": "你的核心能量如参天大树：正直、进取、有开拓力。适合在混沌中立旗，带领他人走出新路。",
        "career": "适合创业、产品、教育、战略与环保相关赛道。避免长期困在过度琐碎、无法决策的岗位。",
        "relationship": "情感中需要空间与尊重。你愿意保护对方，但也怕被束缚。坦诚沟通比牺牲自己更有效。",
        "advice": "2026–2027 宜主动布局长期项目，少与人硬碰硬。以柔克刚，把锋芒用在创造而非对抗。",
        "colors": ["青绿", "碧蓝", "木纹棕"],
        "directions": ["东方", "东南方"],
        "elements": ["木", "水"],
    },
    "乙": {
        "title": "藤萝乙木 · 柔中带韧",
        "essence": "你的能量如藤萝花草：敏锐、适应力强、审美细腻。表面柔软，内里有极强的生命韧性。",
        "career": "适合设计、咨询、内容、医疗康养、品牌与人际协作。你的优势是连接资源、把复杂关系理顺。",
        "relationship": "体贴且共情，但容易过度迁就。建立边界后，关系反而更稳。",
        "advice": "2026–2027 适合深化专业壁垒，把灵活变成系统。避免同时开启过多方向导致能量分散。",
        "colors": ["嫩绿", "杏黄", "浅青"],
        "directions": ["东方", "东南方"],
        "elements": ["木", "水"],
    },
    "丙": {
        "title": "太阳丙火 · 照见万物",
        "essence": "你的能量如烈日：热情、外放、感染力强。你天生能点燃气氛，也容易把理想当成燃料。",
        "career": "适合舞台、传播、销售、领导与高曝光岗位。需要搭配冷静的执行搭档，防止虎头蛇尾。",
        "relationship": "直球、热烈，渴望被看见。学会倾听与降温，感情会更长久。",
        "advice": "2026–2027 把热情落成节奏：固定输出、固定复盘。避免情绪化决策。",
        "colors": ["朱红", "橙金", "暖白"],
        "directions": ["南方"],
        "elements": ["火", "木"],
    },
    "丁": {
        "title": "灯烛丁火 · 内照明灯",
        "essence": "你的能量如夜灯：细腻、洞察、有温度。不靠声量取胜，而靠把一件事照亮到足够深。",
        "career": "适合研究、写作、心理、艺术、精密技术。适合小而美的专业品牌，而非纯体量竞争。",
        "relationship": "敏感而忠诚。需要安全感与精神共鸣，最怕被忽视。",
        "advice": "2026–2027 适合把隐性才华产品化。保护作息与情绪边界，火弱时先养精而非硬撑。",
        "colors": ["暖橙", "烛金", "浅粉"],
        "directions": ["南方", "东方"],
        "elements": ["火", "木"],
    },
    "戊": {
        "title": "城垣戊土 · 承载山河",
        "essence": "你的能量如高山厚土：稳重、可靠、有担当。别人把你当根据地，你也需要学会不过度承载。",
        "career": "适合管理、地产、金融稳健板块、运营中台、公共事务。你擅长把混乱变成秩序。",
        "relationship": "务实、护短，表达含蓄。主动说出感受，能避免被误认为冷淡。",
        "advice": "2026–2027 宜巩固基本盘后再扩张。减少无谓承诺，把资源留给真正的长期同盟。",
        "colors": ["赭石", "土黄", "岩灰"],
        "directions": ["中央", "西南", "东北"],
        "elements": ["土", "火"],
    },
    "己": {
        "title": "田园己土 · 化育万物",
        "essence": "你的能量如田园沃土：包容、滋养、善于整合。你能把碎片变成系统，把人变成团队。",
        "career": "适合人力、教育、社群、农业食品、客户成功。避免被所有人的情绪同时占用。",
        "relationship": "体贴到容易忘我。先把自己照顾好，才能持续给他人稳定感。",
        "advice": "2026–2027 适合做“连接者”与“转化者”。建立筛选机制，只滋养值得深耕的关系与项目。",
        "colors": ["暖米", "褐金", "浅杏"],
        "directions": ["西南", "东北"],
        "elements": ["土", "火"],
    },
    "庚": {
        "title": "剑锋庚金 · 斩断混沌",
        "essence": "你的能量如精钢：果断、原则强、执行力高。适合攻坚克难，也需防止锋芒伤己。",
        "career": "适合法律、工程、金融交易、手术级专业、改革型管理。用规则与标准放大优势。",
        "relationship": "爱恨分明。学会把批评换成请求，亲密关系会柔软许多。",
        "advice": "2026–2027 宜精炼技能、减少多线作战。真正的力量来自精准一击，而非处处开刃。",
        "colors": ["银白", "冷灰", "玄金"],
        "directions": ["西方", "西北"],
        "elements": ["金", "土"],
    },
    "辛": {
        "title": "珠玉辛金 · 锋芒内敛",
        "essence": "你的能量如珠玉：精致、挑剔、品味高。你追求品质与尊严，对粗糙的环境会本能远离。",
        "career": "适合珠宝美学、精品品牌、审计、工艺、高端服务。用细节建立不可替代性。",
        "relationship": "外表冷静，内心极重承诺。需要被欣赏，而不是被改造。",
        "advice": "2026–2027 把审美变成方法论。避免过度内耗，选择能匹配你标准的人和舞台。",
        "colors": ["珍珠白", "香槟金", "浅银"],
        "directions": ["西方"],
        "elements": ["金", "土"],
    },
    "壬": {
        "title": "江海壬水 · 智涌万川",
        "essence": "你的能量如江海：智慧、流动、格局大。思维快、点子多，关键是把水流引入河道。",
        "career": "适合战略、投资、传媒、外交、流动型商务。你适合跨界，但需要阶段性收口。",
        "relationship": "自由且深情。给彼此空间，同时建立固定仪式感，关系更安稳。",
        "advice": "2026–2027 把灵感写成计划，把计划做成复盘。流动不是散漫，而是可控的潮汐。",
        "colors": ["玄蓝", "墨黑", "深青"],
        "directions": ["北方"],
        "elements": ["水", "金"],
    },
    "癸": {
        "title": "雨露癸水 · 润物无声",
        "essence": "你的能量如夜雨：直觉强、共情深、创造力暗涌。你看见别人看不见的情绪与趋势。",
        "career": "适合心理、艺术、研究、玄学咨询、数据洞察。适合深度工作，不适合纯消耗型社交。",
        "relationship": "内心戏丰富。找到能接住你感受的人，比追求热闹更重要。",
        "advice": "2026–2027 把直觉验证为方法。规律作息与身体训练能稳住水性，避免情绪随潮起落。",
        "colors": ["雾蓝", "月白", "银灰"],
        "directions": ["北方", "西方"],
        "elements": ["水", "金"],
    },
}

def get_shi_shen_cn(day_gan, target_gan):
    if not day_gan or not target_gan:
        return ""
    day_wx, target_wx = GAN_WU_XING[day_gan], GAN_WU_XING[target_gan]
    same_yy = GAN_YIN_YANG[day_gan] == GAN_YIN_YANG[target_gan]
    if day_wx == target_wx:
        return "比肩" if same_yy else "劫财"
    if WU_XING_SHENG[day_wx] == target_wx:
        return "食神" if same_yy else "伤官"
    if WU_XING_KE[day_wx] == target_wx:
        return "偏财" if same_yy else "正财"
    if WU_XING_KE[target_wx] == day_wx:
        return "七杀" if same_yy else "正官"
    if WU_XING_SHENG[target_wx] == day_wx:
        return "偏印" if same_yy else "正印"
    return ""


def get_time_gan_zhi(eight_char, lunar):
    """获取时辰干支。

    lunar_python 的 EightChar 没有 getHour()，调用会 AttributeError。
    时柱官方方法是 getTime()；部分资料误写为 getTimes()。
    getTimes() 实际在 Lunar 对象上，返回当天时辰列表。
    """
    for name in ("getTimes", "getTime"):
        fn = getattr(eight_char, name, None)
        if not callable(fn):
            continue
        value = fn()
        if isinstance(value, str) and len(value) >= 2:
            return value

    times_fn = getattr(lunar, "getTimes", None)
    if callable(times_fn):
        times_fn()

    time_obj = lunar.getTime()
    if hasattr(time_obj, "getGanZhi"):
        return time_obj.getGanZhi()
    return lunar.getTimeInGanZhi()


def list_day_times(lunar):
    times_fn = getattr(lunar, "getTimes", None)
    if not callable(times_fn):
        return []
    result = []
    for item in times_fn():
        result.append({
            "gan_zhi": item.getGanZhi() if hasattr(item, "getGanZhi") else str(item),
            "zhi": item.getZhi() if hasattr(item, "getZhi") else "",
        })
    return result


class UserData(BaseModel):
    name: str = "User"
    year: int = Field(..., ge=1900, le=2100)
    month: int = Field(..., ge=1, le=12)
    day: int = Field(..., ge=1, le=31)
    hour: int = Field(..., ge=0, le=23)
    gender: int = Field(1, ge=0, le=1)
    api_key: str = ""


class BirthChartInput(BaseModel):
    year: int = Field(..., ge=1900, le=2100, description="公历年")
    month: int = Field(..., ge=1, le=12, description="公历月")
    day: int = Field(..., ge=1, le=31, description="公历日")
    hour: int = Field(..., ge=0, le=23, description="公历时（0-23）")
    gender: int = Field(1, ge=0, le=1, description="1 男 / 0 女")
    name: str = "Seeker"


def build_pillar(label, gan_zhi, shi_shen_cn, na_yin):
    gan = gan_zhi[0]
    zhi = gan_zhi[1] if len(gan_zhi) > 1 else ""
    return {
        "label": label,
        "gan_zhi": gan_zhi,
        "gan": gan,
        "zhi": zhi,
        "shi_shen": shi_shen_cn,
        "shi_shen_en": SHI_SHEN_EN.get(shi_shen_cn, ""),
        "na_yin": na_yin or "",
        "wu_xing": WU_XING_CN.get(GAN_WU_XING.get(gan, ""), ""),
    }


def calculate_bazi_data(year, month, day, hour, gender):
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    lunar = solar.getLunar()
    eight_char = lunar.getEightChar()

    y_gz = eight_char.getYear()
    m_gz = eight_char.getMonth()
    d_gz = eight_char.getDay()
    h_gz = get_time_gan_zhi(eight_char, lunar)
    day_gan = d_gz[0]

    y_ss = getattr(eight_char, "getYearShiShenGan", lambda: get_shi_shen_cn(day_gan, y_gz[0]))()
    m_ss = getattr(eight_char, "getMonthShiShenGan", lambda: get_shi_shen_cn(day_gan, m_gz[0]))()
    h_ss = getattr(eight_char, "getTimeShiShenGan", lambda: get_shi_shen_cn(day_gan, h_gz[0]))()

    yun = eight_char.getYun(gender)
    da_yun = []
    for dy in yun.getDaYun()[1:6]:
        da_yun.append({
            "start_age": dy.getStartAge(),
            "gan_zhi": dy.getGanZhi(),
        })

    guide = DAY_MASTER_GUIDANCE.get(day_gan, DAY_MASTER_GUIDANCE["甲"])
    gender_label = "乾造（男）" if gender == 1 else "坤造（女）"

    pillars = {
        "year": build_pillar("年柱", y_gz, y_ss, eight_char.getYearNaYin()),
        "month": build_pillar("月柱", m_gz, m_ss, eight_char.getMonthNaYin()),
        "day": build_pillar("日柱", d_gz, "日主", eight_char.getDayNaYin()),
        "hour": build_pillar("时柱", h_gz, h_ss, eight_char.getTimeNaYin()),
    }

    return {
        "day_master": GAN_CN_TO_EN.get(day_gan, day_gan),
        "day_master_gan": day_gan,
        "day_master_element": WU_XING_CN.get(GAN_WU_XING[day_gan], ""),
        "four_pillars": f"Year: {y_gz}, Month: {m_gz}, Day: {d_gz}, Hour: {h_gz}",
        "pillars": pillars,
        "archetypes": f"Ancestral: {SHI_SHEN_EN.get(y_ss, y_ss)}, Mindset: {SHI_SHEN_EN.get(m_ss, m_ss)}, Future/Career: {SHI_SHEN_EN.get(h_ss, h_ss)}",
        "life_cycles": " -> ".join(item["gan_zhi"] for item in da_yun),
        "da_yun": da_yun,
        "start_age": yun.getStartYear(),
        "solar": f"{year}-{month:02d}-{day:02d} {hour:02d}:00",
        "lunar": lunar.toString(),
        "gender": gender,
        "gender_label": gender_label,
        "day_times": list_day_times(lunar),
        "guardian": {
            "title": guide["title"],
            "essence": guide["essence"],
            "career": guide["career"],
            "relationship": guide["relationship"],
            "advice": guide["advice"],
            "lucky_colors": guide["colors"],
            "lucky_directions": guide["directions"],
            "support_elements": guide["elements"],
        },
    }


@app.get("/", response_class=HTMLResponse)
def root():
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_path, media_type="text/html")


@app.post("/generate_guardian_guidance")
def generate_guardian_guidance(payload: BirthChartInput):
    try:
        chart = calculate_bazi_data(
            payload.year, payload.month, payload.day, payload.hour, payload.gender
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"八字排盘失败：{exc}") from exc

    return {
        "status": "success",
        "name": payload.name,
        "bazi": chart,
        "guidance": chart["guardian"],
    }


@app.post("/generate_report")
def generate_report(user: UserData):
    bazi_info = calculate_bazi_data(user.year, user.month, user.day, user.hour, user.gender)

    prompt = f"""
You are a world-class spiritual mentor and energy psychology expert.
Generate a personalized, empathetic, and deeply insightful "Core Energy & Self-Discovery Report" for {user.name}.

User Chart Profile:
- Core Element (Day Master): {bazi_info['day_master']}
- Four Pillars Pattern: {bazi_info['four_pillars']}
- Inner Archetypes: {bazi_info['archetypes']}
- Life Energy Cycles: {bazi_info['life_cycles']}

Report Requirements:
1. Tone: Empathetic, inspiring, professional, psychological, avoiding direct references to "superstition" or "fatalism". Use terms like "elemental balance", "energy resonance", and "inner potential".
2. Structure:
   - Part 1: Your Core Energy Essence & Hidden Talent
   - Part 2: Career & Financial Flow (Where your fortune resonates best)
   - Part 3: Relationship & Emotional Harmony
   - Part 4: Strategic Advice for 2026-2027
3. Make it engaging, highly specific, and actionable.
"""
    if user.api_key:
        try:
            response = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {user.api_key}"},
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                },
                timeout=30,
            )
            ai_content = response.json()["choices"][0]["message"]["content"]
            return {"status": "success", "user": user.name, "report": ai_content, "raw_bazi": bazi_info}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"AI API Error: {exc}") from exc

    return {
        "status": "success",
        "user": user.name,
        "bazi_chart": bazi_info,
        "note": "Pass 'api_key' to generate full AI report.",
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
