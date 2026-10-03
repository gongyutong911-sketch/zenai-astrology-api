# -*- coding: utf-8 -*-
from datetime import datetime
from lunar_python import Solar, Lunar

def get_bazi_profile(year: int, month: int, day: int, hour: int):
    """
    根据公历年月日时计算八字命盘及今日干支能量
    """
    # 1. 构造用户出生公历对象
    solar = Solar.fromYmdHms(year, month, day, hour, 0, 0)
    
    # 2. 转为农历/八字对象 (已修复 AttributeError)
    lunar = solar.getLunar()
    
    # 获取八字四柱
    bazi = lunar.getEightChar()
    bazi_str = f"{bazi.getYear()}年 {bazi.getMonth()}月 {bazi.getDay()}日 {bazi.getTime()}时"
    
    # 日主（日干）
    day_master = bazi.getDayGan()
    
    # 3. 获取今日阳历与干支信息
    now = datetime.now()
    today_solar = Solar.fromYmdHms(now.year, now.month, now.day, now.hour, now.minute, now.second)
    today_lunar = today_solar.getLunar()
    today_ganzhi = f"{today_lunar.getYearInGanZhi()}年 {today_lunar.getMonthInGanZhi()}月 {today_lunar.getDayInGanZhi()}日"
    
    return {
        "solar_date": f"{year}-{month:02d}-{day:02d} {hour:02d}:00",
        "lunar_date": f"{lunar.getYearInChinese()}年 {lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "bazi_str": bazi_str,
        "day_master": day_master,
        "today_solar": now.strftime("%Y-%m-%d"),
        "today_ganzhi": today_ganzhi
    }