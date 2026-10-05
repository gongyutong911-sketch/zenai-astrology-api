import argparse
import math
from datetime import datetime, timedelta
from typing import Optional

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

# 北京时间的中央经线。经度每偏 1°，平太阳时相差 4 分钟。
BEIJING_MERIDIAN = 120.0
ZI_HOUR_EARLY = "early"
ZI_HOUR_LATE = "late"
ZI_HOUR_LABELS = {
    ZI_HOUR_EARLY: "早子时（23点后日柱仍属当日）",
    ZI_HOUR_LATE: "晚子时（23点后日柱属次日）",
}

# 月柱只在「节」交接，不在「气」交接。顺序对应寅月到丑月。
JIE_MONTH_ZHI = {
    "立春": "寅", "惊蛰": "卯", "清明": "辰", "立夏": "巳",
    "芒种": "午", "小暑": "未", "立秋": "申", "白露": "酉",
    "寒露": "戌", "立冬": "亥", "大雪": "子", "小寒": "丑",
}

# 东经为正。纬度只随城市记下，真太阳时校正用经度。
BIRTH_CITIES = {
    "北京": (116.41, 39.90),
    "天津": (117.20, 39.13),
    "上海": (121.47, 31.23),
    "重庆": (106.55, 29.56),
    "广州": (113.26, 23.13),
    "深圳": (114.06, 22.54),
    "成都": (104.07, 30.67),
    "杭州": (120.16, 30.25),
    "南京": (118.80, 32.06),
    "武汉": (114.31, 30.59),
    "西安": (108.94, 34.34),
    "郑州": (113.63, 34.75),
    "长沙": (112.94, 28.23),
    "沈阳": (123.43, 41.80),
    "哈尔滨": (126.53, 45.80),
    "长春": (125.32, 43.82),
    "昆明": (102.71, 25.04),
    "乌鲁木齐": (87.62, 43.83),
    "拉萨": (91.11, 29.65),
    "兰州": (103.83, 36.06),
    "西宁": (101.78, 36.62),
    "银川": (106.23, 38.49),
    "呼和浩特": (111.75, 40.84),
    "南宁": (108.37, 22.82),
    "海口": (110.32, 20.04),
    "贵阳": (106.63, 26.65),
    "福州": (119.30, 26.08),
    "厦门": (118.09, 24.48),
    "青岛": (120.38, 36.07),
    "大连": (121.62, 38.91),
    "济南": (117.12, 36.65),
    "合肥": (117.23, 31.82),
    "南昌": (115.86, 28.68),
    "石家庄": (114.51, 38.04),
    "太原": (112.55, 37.87),
    "台北": (121.56, 25.04),
    "香港": (114.17, 22.32),
    "澳门": (113.54, 22.19),
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


def normalize_zi_hour(mode: str) -> str:
    """早子时：23:00 起日柱仍属当日。晚子时：23:00 起日柱属次日。"""
    chosen = (mode or ZI_HOUR_EARLY).strip() or ZI_HOUR_EARLY
    if chosen not in ZI_HOUR_LABELS:
        raise ValueError("子时划分只能是早子时或晚子时")
    return chosen


def resolve_birth_place(
    birth_city: Optional[str] = None,
    longitude: Optional[float] = None,
    latitude: Optional[float] = None,
) -> dict:
    """城市换算经纬度。显式经度优先；都没给时用东经 120°。"""
    city = (birth_city or "").strip() or None
    city_longitude = None
    city_latitude = None
    if city in BIRTH_CITIES:
        city_longitude, city_latitude = BIRTH_CITIES[city]
    elif city and longitude is None:
        raise ValueError("出生城市无法对应经度，请改填经度")
    if longitude is None:
        longitude = city_longitude if city_longitude is not None else BEIJING_MERIDIAN
    if latitude is None:
        latitude = city_latitude
    try:
        longitude = float(longitude)
        latitude = None if latitude is None else float(latitude)
    except (TypeError, ValueError) as exc:
        raise ValueError("经度或纬度无法读取") from exc
    if not -180 <= longitude <= 180:
        raise ValueError("经度需在 -180 到 180 之间")
    if latitude is not None and not -90 <= latitude <= 90:
        raise ValueError("纬度需在 -90 到 90 之间")
    return {
        "birth_city": city,
        "longitude": round(longitude, 4),
        "latitude": None if latitude is None else round(latitude, 4),
    }


def equation_of_time_minutes(moment: datetime) -> float:
    """均时差（分钟）。视太阳时 = 平太阳时 + 均时差。采用 NOAA 近似。"""
    day_of_year = moment.timetuple().tm_yday
    hour = moment.hour + moment.minute / 60 + moment.second / 3600
    gamma = 2 * math.pi / 365 * (day_of_year - 1 + (hour - 12) / 24)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )


def true_solar_datetime(moment: datetime, longitude: float) -> datetime:
    """北京时间转到当地真太阳时，结果精确到秒。"""
    offset_minutes = 4 * (float(longitude) - BEIJING_MERIDIAN) + equation_of_time_minutes(moment)
    return moment + timedelta(seconds=int(round(offset_minutes * 60)))


def _clock(birth_date: str, birth_time: str) -> datetime:
    try:
        year_text, month_text, day_text = birth_date.strip().split("-")
        time_parts = birth_time.strip().split(":")
        hour = int(time_parts[0])
        minute = int(time_parts[1]) if len(time_parts) > 1 else 0
        second = int(time_parts[2]) if len(time_parts) > 2 else 0
        return datetime(int(year_text), int(month_text), int(day_text), hour, minute, second)
    except (TypeError, ValueError) as exc:
        raise ValueError("出生日期或时间无法排盘") from exc


def _solar(moment: datetime):
    return Solar.fromYmdHms(
        moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second
    )


def jieqi_moment(year: int, name: str) -> datetime:
    """取出某年节气的北京时间，精确到秒。"""
    table = _solar(datetime(year, 6, 1, 12, 0, 0)).getLunar().getJieQiTable()
    found = table.get(name)
    if found is None or found.getYear() != year:
        raise ValueError("节气时刻无法确定")
    return datetime(
        found.getYear(), found.getMonth(), found.getDay(),
        found.getHour(), found.getMinute(), found.getSecond(),
    )


def _hour_zhi_index(hour: int, minute: int) -> int:
    minutes = hour * 60 + minute
    if minutes >= 23 * 60 or minutes < 60:
        return 0
    return (minutes - 60) // 120 + 1


def _hour_gan_zhi(day_gan: str, moment: datetime) -> str:
    """时干跟随实际采用的日干，避免 23 点被固定成次日。"""
    zhi_index = _hour_zhi_index(moment.hour, moment.minute)
    gan_index = (GAN.index(day_gan) % 5) * 2 + zhi_index
    return GAN[gan_index % 10] + ZHI[zhi_index]


def _fmt(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def cast_chart(
    birth_date: str,
    birth_time: str,
    gender: str,
    longitude: Optional[float] = None,
    latitude: Optional[float] = None,
    birth_city: Optional[str] = None,
    zi_hour_mode: str = ZI_HOUR_EARLY,
) -> dict:
    """用历法排出四柱、十神、旺衰和大运。干支来自排盘，不由模型生成。

    年柱、月柱比较出生瞬间与节气瞬间，节气取到秒。
    日柱、时柱用真太阳时，并按早晚子时决定 23:00 是否换日。
    """
    place = resolve_birth_place(birth_city, longitude, latitude)
    mode = normalize_zi_hour(zi_hour_mode)
    try:
        clock = _clock(birth_date, birth_time)
        apparent = true_solar_datetime(clock, place["longitude"])
        clock_char = _solar(clock).getLunar().getEightChar()
        apparent_char = _solar(apparent).getLunar().getEightChar()
        apparent_char.setSect(1 if mode == ZI_HOUR_LATE else 2)
        opened = _solar(clock).getLunar().getPrevJie()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("出生日期或时间无法排盘") from exc
    gender_code, gender_label = _gender_code(gender)
    day_gan_zhi = apparent_char.getDay()
    day_gan = day_gan_zhi[0]
    gan_zhi = {
        "year": clock_char.getYear(),
        "month": clock_char.getMonth(),
        "day": day_gan_zhi,
        "hour": _hour_gan_zhi(day_gan, apparent),
    }
    pillars = {
        name: _pillar(value, day_gan, name == "day")
        for name, value in gan_zhi.items()
    }
    yun = clock_char.getYun(gender_code)
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
    age = today.year - clock.year
    if (today.month, today.day) < (clock.month, clock.day):
        age -= 1
    current = None
    for item in da_yun:
        if item["start_age"] <= age:
            current = item["gan_zhi"]
    liu_nian = Solar.fromYmd(today.year, today.month, today.day).getLunar().getEightChar().getYear()
    jie_solar = opened.getSolar()
    jie_at = datetime(
        jie_solar.getYear(), jie_solar.getMonth(), jie_solar.getDay(),
        jie_solar.getHour(), jie_solar.getMinute(), jie_solar.getSecond(),
    )
    offset_minutes = 4 * (place["longitude"] - BEIJING_MERIDIAN)
    return {
        "solar": clock.strftime("%Y-%m-%d %H:%M"),
        "clock_time": _fmt(clock),
        "true_solar_time": _fmt(apparent),
        "longitude": place["longitude"],
        "latitude": place["latitude"],
        "birth_city": place["birth_city"],
        "longitude_offset_minutes": round(offset_minutes, 4),
        "equation_of_time_minutes": round(equation_of_time_minutes(clock), 4),
        "zi_hour_mode": mode,
        "zi_hour_label": ZI_HOUR_LABELS[mode],
        "month_jie": opened.getName(),
        "month_jie_at": _fmt(jie_at),
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


def compose_deep_report(
    birth_date: str,
    birth_time: str,
    gender: str,
    question: str = "",
    longitude: Optional[float] = None,
    latitude: Optional[float] = None,
    birth_city: Optional[str] = None,
    zi_hour_mode: str = ZI_HOUR_EARLY,
) -> dict:
    """把已经排好的盘写成四个章节。章节只解释盘里的干支、十神和旺衰。"""
    chart = cast_chart(
        birth_date,
        birth_time,
        gender,
        longitude=longitude,
        latitude=latitude,
        birth_city=birth_city,
        zi_hour_mode=zi_hour_mode,
    )
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
                f"钟面按北京时间 {chart['clock_time']} 记录，真太阳时为 {chart['true_solar_time']}"
                f"（经度 {chart['longitude']}°，经度差 {chart['longitude_offset_minutes']} 分，均时差 {chart['equation_of_time_minutes']} 分）。"
                f"月柱以{chart['month_jie']}交节 {chart['month_jie_at']} 为界，子时按{chart['zi_hour_label']}。"
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


def run_bazi(year, month, day, hour, minute=0, gender=1, longitude=None, zi_hour_mode=ZI_HOUR_EARLY):
    gender_name = "male" if gender == 1 else "female"
    chart = cast_chart(
        f"{year:04d}-{month:02d}-{day:02d}",
        f"{hour:02d}:{minute:02d}",
        gender_name,
        longitude=longitude,
        zi_hour_mode=zi_hour_mode,
    )
    pillars = chart["pillars"]
    print("=" * 60)
    print("       【 ZenAI 命理排盘系统 - 核心测试 】")
    print(f" 公历生日：{chart['solar']}  真太阳时：{chart['true_solar_time']}  性别：{chart['gender_label']}")
    print(f" 经度：{chart['longitude']}  交节：{chart['month_jie']} {chart['month_jie_at']}  {chart['zi_hour_label']}")
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
    parser.add_argument("--longitude", type=float, default=None)
    parser.add_argument("--zi-hour", choices=(ZI_HOUR_EARLY, ZI_HOUR_LATE), default=ZI_HOUR_EARLY)
    args = parser.parse_args()

    run_bazi(
        args.year, args.month, args.day, args.hour,
        gender=args.gender, longitude=args.longitude, zi_hour_mode=args.zi_hour,
    )

