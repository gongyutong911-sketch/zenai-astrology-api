"""真太阳时、节气交节和早晚子时的边界。"""

import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"

import bazi
import database
import main

client = TestClient(main.app)


def test_equation_of_time_stays_near_the_published_extrema():
    assert bazi.equation_of_time_minutes(datetime(2024, 2, 11, 12)) == pytest.approx(-14.2, abs=1)
    assert bazi.equation_of_time_minutes(datetime(2024, 4, 15, 12)) == pytest.approx(0, abs=1)
    assert bazi.equation_of_time_minutes(datetime(2024, 11, 3, 12)) == pytest.approx(16.4, abs=1)
    for month, day in ((1, 1), (6, 21), (12, 31)):
        value = bazi.equation_of_time_minutes(datetime(2024, month, day, 12))
        assert -17 < value < 17


def test_longitude_offset_is_four_minutes_per_degree():
    moment = datetime(2024, 6, 15, 12, 0, 0)
    base = bazi.true_solar_datetime(moment, 120)
    east = bazi.true_solar_datetime(moment, 130)
    assert (east - base).total_seconds() == 10 * 4 * 60


def test_standard_meridian_keeps_the_known_chart():
    chart = bazi.cast_chart("1990-01-15", "08:30", "female")
    assert chart["longitude"] == 120
    assert chart["birth_city"] is None
    assert chart["pillars"]["day"]["gan_zhi"] == "庚辰"
    assert chart["pillars"]["month"]["gan_zhi"] == "丁丑"
    assert chart["month_jie"] == "小寒"
    assert len(chart["month_jie_at"]) == 19


def test_true_solar_time_moves_the_hour_pillar_west_of_beijing():
    local = bazi.cast_chart("1990-06-15", "12:00", "female", longitude=120)
    west = bazi.cast_chart("1990-06-15", "12:00", "female", birth_city="乌鲁木齐")
    apparent = datetime.strptime(west["true_solar_time"], "%Y-%m-%d %H:%M:%S")
    assert west["longitude"] == 87.62
    assert west["latitude"] == 43.83
    assert local["pillars"]["hour"]["zhi"] == "午"
    assert west["pillars"]["hour"]["zhi"] == bazi.ZHI[bazi._hour_zhi_index(apparent.hour, apparent.minute)]
    assert west["pillars"]["hour"]["zhi"] != local["pillars"]["hour"]["zhi"]
    assert west["pillars"]["day"]["gan_zhi"] == local["pillars"]["day"]["gan_zhi"]


def test_month_pillar_switches_on_the_lichun_second():
    moment = bazi.jieqi_moment(2024, "立春")
    before = moment - timedelta(seconds=1)
    opened = bazi.cast_chart(moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M:%S"), "male", longitude=120)
    closed = bazi.cast_chart(before.strftime("%Y-%m-%d"), before.strftime("%H:%M:%S"), "male", longitude=120)
    assert opened["month_jie"] == "立春"
    assert opened["month_jie_at"] == moment.strftime("%Y-%m-%d %H:%M:%S")
    assert opened["pillars"]["month"]["zhi"] == "寅"
    assert closed["month_jie"] == "小寒"
    assert closed["pillars"]["month"]["zhi"] == "丑"
    assert opened["pillars"]["year"]["gan_zhi"] != closed["pillars"]["year"]["gan_zhi"]


def test_month_pillar_switches_on_the_jingzhe_second():
    moment = bazi.jieqi_moment(2024, "惊蛰")
    before = moment - timedelta(seconds=1)
    opened = bazi.cast_chart(moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M:%S"), "female", longitude=120)
    closed = bazi.cast_chart(before.strftime("%Y-%m-%d"), before.strftime("%H:%M:%S"), "female", longitude=120)
    assert opened["month_jie"] == "惊蛰"
    assert opened["pillars"]["month"]["zhi"] == "卯"
    assert closed["month_jie"] == "立春"
    assert closed["pillars"]["month"]["zhi"] == "寅"
    assert opened["pillars"]["year"]["gan_zhi"] == closed["pillars"]["year"]["gan_zhi"]


def test_late_zi_hour_moves_the_day_pillar_only_between_23_and_midnight():
    early = bazi.cast_chart("1990-01-15", "23:30", "female", longitude=120, zi_hour_mode="early")
    late = bazi.cast_chart("1990-01-15", "23:30", "female", longitude=120, zi_hour_mode="late")
    same_day = bazi.cast_chart("1990-01-15", "12:00", "female", longitude=120)
    next_day = bazi.cast_chart("1990-01-16", "12:00", "female", longitude=120)
    assert datetime.strptime(early["true_solar_time"], "%Y-%m-%d %H:%M:%S").hour == 23
    assert early["pillars"]["day"]["gan_zhi"] == same_day["pillars"]["day"]["gan_zhi"] == "庚辰"
    assert late["pillars"]["day"]["gan_zhi"] == next_day["pillars"]["day"]["gan_zhi"]
    assert early["pillars"]["hour"]["zhi"] == late["pillars"]["hour"]["zhi"] == "子"
    assert early["pillars"]["hour"]["gan"] != late["pillars"]["hour"]["gan"]

    after = bazi.cast_chart("1990-01-16", "00:30", "female", longitude=120, zi_hour_mode="early")
    after_late = bazi.cast_chart("1990-01-16", "00:30", "female", longitude=120, zi_hour_mode="late")
    assert after["pillars"]["day"]["gan_zhi"] == after_late["pillars"]["day"]["gan_zhi"] == next_day["pillars"]["day"]["gan_zhi"]
    assert after["pillars"]["hour"]["zhi"] == "子"


def test_unknown_city_and_out_of_range_longitude_are_rejected():
    with pytest.raises(ValueError, match="经度"):
        bazi.resolve_birth_place("不存在的城市")
    with pytest.raises(ValueError, match="经度"):
        bazi.resolve_birth_place(longitude=181)
    with pytest.raises(ValueError, match="子时"):
        bazi.normalize_zi_hour("noon")


def test_deep_report_uses_birth_place_before_spending_a_credit(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    headers = {"X-API-Key": "test-secret"}
    with patch.object(main, "get_astrology_energy_guidance", return_value={
        "core_energy": "核心能量",
        "career_guidance": "事业指引",
        "relationship_advice": "关系建议",
        "wealth_flow": "财富能量",
        "action_tips": "行动锦囊",
        "lucky_elements": "幸运密码",
    }):
        created = client.post("/api/energy-guidance", json={
            "birth_date": "1990-01-15",
            "birth_time": "08:30",
            "gender": "female",
            "question": "今日能量指引",
        }, headers=headers)
    token = created.json()["user_token"]
    database.grant_deep_credits(quantity=1, user_token=token)

    rejected = client.post("/api/deep-report", json={
        "birth_date": "1990-06-15",
        "birth_time": "12:00",
        "gender": "female",
        "longitude": 400,
        "user_token": token,
    }, headers=headers)
    assert rejected.status_code == 400
    assert "经度" in rejected.json()["detail"]

    opened = client.post("/api/deep-report", json={
        "birth_date": "1990-06-15",
        "birth_time": "12:00",
        "gender": "female",
        "birth_city": "乌鲁木齐",
        "zi_hour_mode": "late",
        "user_token": token,
    }, headers=headers)
    assert opened.status_code == 200
    chart = opened.json()["chart"]
    assert chart["birth_city"] == "乌鲁木齐"
    assert chart["longitude"] == 87.62
    assert chart["true_solar_time"] != chart["clock_time"]
    assert "真太阳时" in opened.json()["chapters"][0]["body"]
    assert opened.json()["one_time_credits"] == 0
