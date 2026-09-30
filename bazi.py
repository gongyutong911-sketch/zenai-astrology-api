import argparse
from datetime import datetime
from lunar_python import Lunar, Solar

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

def run_bazi(year, month, day, hour, minute=0, gender=1):
    solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
    lunar = solar.getLunar()
    eight_char = lunar.getEightChar()

    # EightChar 无 getHour()；时柱用 getTime()。getTimes() 在 Lunar 上，为当天时辰列表。
    h_gz = eight_char.getTime() if hasattr(eight_char, "getTime") else lunar.getTimeInGanZhi()
    if hasattr(lunar, "getTimes"):
        lunar.getTimes()
    y_gz, m_gz, d_gz = eight_char.getYear(), eight_char.getMonth(), eight_char.getDay()
    day_gan = d_gz[0]

    y_ss = get_shi_shen(day_gan, y_gz[0])
    m_ss = get_shi_shen(day_gan, m_gz[0])
    h_ss = get_shi_shen(day_gan, h_gz[0])

    print("=" * 60)
    print(f"       【 ZenAI 命理排盘系统 - 核心测试 】")
    print(f" 公历生日：{year}年{month}月{day}日 {hour}:{minute:02d}  性别：{'乾造(男)' if gender == 1 else '坤造(女)'}")
    print("=" * 60)
    print(f"{'项目':<8}{'年柱':<10}{'月柱':<10}{'日柱':<10}{'时柱':<10}")
    print("-" * 60)
    print(f"{'十神':<8}{y_ss:<10}{m_ss:<10}{'日主':<10}{h_ss:<10}")
    print(f"{'干支':<8}{y_gz:<10}{m_gz:<10}{d_gz:<10}{h_gz:<10}")
    print("-" * 60)
    
    # 获取大运
    yun = eight_char.getYun(gender)
    print(f"起运年龄：大约 {yun.getStartYear()} 岁起运")
    da_yun_list = yun.getDaYun()
    dy_strs = [f"{dy.getStartAge()}岁 {dy.getGanZhi()}" for dy in da_yun_list[1:9]]
    print("大运流程：" + " -> ".join(dy_strs))
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

