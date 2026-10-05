import argparse
from datetime import datetime
from lunar_python import Solar

GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

GAN_WU_XING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土", "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
GAN_YIN_YANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1, "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}

ZHI_CANG_GAN = {
    "子": ["癸"], "丑": ["己", "癸", "辛"], "寅": ["甲", "丙", "戊"], "卯": ["乙"],
    "辰": ["戊", "乙", "癸"], "巳": ["丙", "戊", "庚"], "午": ["丁", "己"],
    "未": ["己", "丁", "乙"], "申": ["庚", "壬", "戊"], "酉": ["辛"],
    "戌": ["戊", "辛", "丁"], "亥": ["壬", "甲"]
}

WU_XING_SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
WU_XING_KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

MONTH_ELEMENT = {
    "寅": "木", "卯": "木", "辰": "土",
    "巳": "火", "午": "火", "未": "土",
    "申": "金", "酉": "金", "戌": "土",
    "亥": "水", "子": "水", "丑": "土",
}


def get_shi_shen(day_gan, target_gan):
    if not day_gan or not target_gan:
        return ""
    day_wx, target_wx = GAN_WU_XING[day_gan], GAN_WU_XING[target_gan]
    same_yy = (GAN_YIN_YANG[day_gan] == GAN_YIN_YANG[target_gan])
    if day_wx == target_wx: return "比肩" if same_yy else "劫财"
    elif WU_XING_SHENG[day_wx] == target_wx: return "食神" if same_yy else "伤官"
    elif WU_XING_KE[day_wx] == target_wx: return "偏财" if same_yy else "正财"
    elif WU_XING_KE[target_wx] == day_wx: return "七杀" if same_yy else "正官"
    elif WU_XING_SHENG[target_wx] == day_wx: return "偏印" if same_yy else "正印"
    return ""


def _pillar(gan_zhi: str, day_gan: str, is_day: bool) -> dict:
    gan, zhi = gan_zhi[0], gan_zhi[1]
    return {
        "gan_zhi": gan_zhi,
        "gan": gan,
        "zhi": zhi,
        "wu_xing": GAN_WU_XING[gan],
        "shi_shen": "日主" if is_day else get_shi_shen(day_gan, gan),
    }


def _strength(day_gan: str, pillars: dict) -> dict:
    """用月令与天干生克给日主一个可复核的旺衰，不交给模型临场编造。"""
    day_wx = GAN_WU_XING[day_gan]
    month_zhi = pillars["month"]["zhi"]
    month_wx = MONTH_ELEMENT[month_zhi]
    score = 0
    factors = []
    if month_wx == day_wx:
        score += 3
        factors.append(f"生于{month_zhi}月，日主{day_wx}得令")
    elif WU_XING_SHENG[month_wx] == day_wx:
        score += 1
        factors.append(f"月令{month_zhi}为{month_wx}，生扶日主{day_wx}")
    elif WU_XING_KE[month_wx] == day_wx:
        score -= 2
        factors.append(f"月令{month_zhi}为{month_wx}，克制日主{day_wx}")
    else:
        factors.append(f"月令{month_zhi}为{month_wx}，日主{day_wx}不得令")
    labels = {"year": "年干", "month": "月干", "hour": "时干"}
    for key, title in labels.items():
        gan = pillars[key]["gan"]
        wx = GAN_WU_XING[gan]
        if wx == day_wx:
            score += 1
            factors.append(f"{title}{gan}{wx}比助日主")
        elif WU_XING_SHENG[wx] == day_wx:
            score += 1
            factors.append(f"{title}{gan}{wx}生扶日主")
        elif WU_XING_KE[wx] == day_wx:
            score -= 1
            factors.append(f"{title}{gan}{wx}克制日主")
    if score >= 3:
        label = "身旺"
    elif score <= 0:
        label = "身弱"
    else:
        label = "中和"
    return {"score": score, "label": label, "factors": factors}


def _gender_code(gender: str) -> tuple:
    if gender == "male":
        return 1, "乾造"
    if gender == "other":
        return 0, "其他（起运按坤造）"
    return 0, "坤造"


def cast_chart(birth_date: str, birth_time: str, gender: str) -> dict:
    """用历法排出四柱、十神、旺衰和大运。干支来自排盘，不由模型生成。"""
    try:
        year_text, month_text, day_text = birth_date.strip().split("-")
        time_parts = birth_time.strip().split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        year, month, day = int(year_text), int(month_text), int(day_text)
        solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
        eight_char = solar.getLunar().getEightChar()
    except Exception as exc:
        raise ValueError("出生日期或时间无法排盘") from exc
    gender_code, gender_label = _gender_code(gender)
    names = ("year", "month", "day", "hour")
    gan_zhi = (
        eight_char.getYear(),
        eight_char.getMonth(),
        eight_char.getDay(),
        eight_char.getTime(),
    )
    day_gan = gan_zhi[2][0]
    pillars = {
        name: _pillar(value, day_gan, name == "day")
        for name, value in zip(names, gan_zhi)
    }
    yun = eight_char.getYun(gender_code)
    da_yun = [
        {
            "start_age": item.getStartAge(),
            "start_year": item.getStartYear(),
            "gan_zhi": item.getGanZhi(),
        }
        for item in yun.getDaYun()[1:9]
        if item.getGanZhi()
    ]
    today = datetime.now()
    age = today.year - year
    if (today.month, today.day) < (month, day):
        age -= 1
    current = None
    for item in da_yun:
        if item["start_age"] <= age:
            current = item["gan_zhi"]
    liu_nian = Solar.fromYmd(today.year, today.month, today.day).getLunar().getEightChar().getYear()
    return {
        "solar": f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}",
        "gender_label": gender_label,
        "day_master": f"{day_gan}{GAN_WU_XING[day_gan]}",
        "pillars": pillars,
        "strength": _strength(day_gan, pillars),
        "da_yun_start_age": yun.getStartYear(),
        "da_yun": da_yun,
        "current_da_yun": current,
        "liu_nian": liu_nian,
        "age": age,
    }


def _roles(chart: dict) -> list:
    found = []
    for key, title in (("year", "年柱"), ("month", "月柱"), ("hour", "时柱")):
        pillar = chart["pillars"][key]
        found.append(f"{title}{pillar['gan_zhi']}，天干{pillar['gan']}为{pillar['shi_shen']}")
    return found


def _stars(chart: dict, names: set) -> list:
    hits = []
    for key, title in (("year", "年干"), ("month", "月干"), ("hour", "时干")):
        pillar = chart["pillars"][key]
        if pillar["shi_shen"] in names:
            hits.append(f"{title}{pillar['gan']}为{pillar['shi_shen']}")
    return hits


def compose_deep_report(birth_date: str, birth_time: str, gender: str, question: str = "") -> dict:
    """把已经排好的盘写成四个章节。章节只解释盘里的干支、十神和旺衰。"""
    chart = cast_chart(birth_date, birth_time, gender)
    pillars = chart["pillars"]
    day = pillars["day"]
    strength = chart["strength"]
    line = "、".join(item["gan_zhi"] for item in (pillars["year"], pillars["month"], day, pillars["hour"]))
    roles = "；".join(_roles(chart))
    focus = (question or "这一次想看清的处境").strip()
    wealth = _stars(chart, {"正财", "偏财"})
    officer = _stars(chart, {"正官", "七杀"})
    output = _stars(chart, {"食神", "伤官"})
    resource = _stars(chart, {"正印", "偏印"})
    wealth_text = "、".join(wealth) if wealth else "天干没有直接露出正财或偏财"
    officer_text = "、".join(officer) if officer else "天干没有直接露出正官或七杀"
    output_text = "、".join(output) if output else "天干没有直接露出食神或伤官"
    resource_text = "、".join(resource) if resource else "天干没有直接露出正印或偏印"
    yun_text = " -> ".join(
        f"{item['start_age']}岁{item['gan_zhi']}" for item in chart["da_yun"]
    )
    current = chart["current_da_yun"] or "尚未进入第一步大运"
    liu_nian_role = get_shi_shen(day["gan"], chart["liu_nian"][0])
    chapters = [
        {
            "key": "personality",
            "title": "性格底色",
            "body": (
                f"这张盘是{chart['gender_label']}，四柱为{line}。"
                f"日主{chart['day_master']}坐{day['zhi']}，{roles}。"
                f"旺衰按月令与天干生克计为{strength['score']}分，判断为{strength['label']}。"
                f"{'；'.join(strength['factors'])}。"
                f"围绕「{focus}」，这种底色更像一种做事的惯性：得助时会把标准做实，受克时则容易把力气用在反复确认上。"
            ),
        },
        {
            "key": "wealth",
            "title": "财富格局",
            "body": (
                f"财富先看财星有没有露在天干：{wealth_text}。"
                f"日主{chart['day_master']}为{strength['label']}，资源位是{resource_text}。"
                "格局上，财更像注意力和边界的分配，而不是一个必然到账的数字。"
                "盘面可见的位置，适合先守住已经在手里的资源，再决定哪一笔投入值得继续。"
            ),
        },
        {
            "key": "career",
            "title": "事业破局",
            "body": (
                f"事业看官杀与食伤怎么摆：{officer_text}；{output_text}。"
                f"月柱{pillars['month']['gan_zhi']}的天干是{pillars['month']['shi_shen']}，这是事业课题最靠近日常的一柱。"
                f"以「{focus}」来看，破局点不在把所有责任一次揽完，而在把{pillars['month']['shi_shen']}所代表的权责写成一件边界清楚、做完能看见结果的事。"
            ),
        },
        {
            "key": "luck_cycles",
            "title": "流年大运",
            "body": (
                f"大约{chart['da_yun_start_age']}岁起运。大运依次为：{yun_text}。"
                f"按公历年龄约{chart['age']}岁，当前所在大运是{current}。"
                f"今年流年{chart['liu_nian']}，流年天干对日主{day['gan']}为{liu_nian_role}。"
                "这一步适合用来对照节奏，而不是把某一年写成不可更改的结果。"
            ),
        },
    ]
    return {"chart": chart, "chapters": chapters}


def run_bazi(year, month, day, hour, minute=0, gender=1):
    gender_name = "male" if gender == 1 else "female"
    chart = cast_chart(
        f"{year:04d}-{month:02d}-{day:02d}",
        f"{hour:02d}:{minute:02d}",
        gender_name,
    )
    pillars = chart["pillars"]
    print("=" * 60)
    print("       【 ZenAI 命理排盘系统 - 核心测试 】")
    print(f" 公历生日：{chart['solar']}  性别：{chart['gender_label']}")
    print("=" * 60)
    print(f"{'项目':<8}{'年柱':<10}{'月柱':<10}{'日柱':<10}{'时柱':<10}")
    print("-" * 60)
    print(
        f"{'十神':<8}{pillars['year']['shi_shen']:<10}{pillars['month']['shi_shen']:<10}"
        f"{'日主':<10}{pillars['hour']['shi_shen']:<10}"
    )
    print(
        f"{'干支':<8}{pillars['year']['gan_zhi']:<10}{pillars['month']['gan_zhi']:<10}"
        f"{pillars['day']['gan_zhi']:<10}{pillars['hour']['gan_zhi']:<10}"
    )
    print("-" * 60)
    print(f"旺衰：{chart['strength']['label']}（{chart['strength']['score']}）")
    print(f"起运年龄：大约 {chart['da_yun_start_age']} 岁起运")
    print("大运流程：" + " -> ".join(f"{item['start_age']}岁 {item['gan_zhi']}" for item in chart["da_yun"]))
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=1995)
    parser.add_argument("--month", type=int, default=10)
    parser.add_argument("--day", type=int, default=20)
    parser.add_argument("--hour", type=int, default=14)
    parser.add_argument("--gender", type=int, default=1)
    args = parser.parse_args()

    run_bazi(args.year, args.month, args.day, args.hour, gender=args.gender)

