"""模拟免费用户、单次深度报告和年订阅分别请求测算接口。"""

import os
from datetime import datetime, timedelta

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"

from unittest.mock import patch

from fastapi.testclient import TestClient

import database
import main

client = TestClient(main.app)

PAYLOAD = {
    "birth_date": "1990-01-15",
    "birth_time": "08:30",
    "gender": "female",
    "question": "今日能量指引",
}

SIX_FIELDS = (
    "core_energy",
    "career_guidance",
    "relationship_advice",
    "wealth_flow",
    "action_tips",
    "lucky_elements",
)

FULL_GUIDANCE = {
    "core_energy": "核心能量",
    "career_guidance": "事业指引",
    "relationship_advice": "关系建议",
    "wealth_flow": "财富能量",
    "action_tips": "行动锦囊",
    "lucky_elements": "幸运密码",
}


def _headers(**extra):
    return {"X-API-Key": "test-secret", **extra}


def _request_guidance(monkeypatch, payload, headers):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(FULL_GUIDANCE)) as mocked:
        response = client.post("/api/energy-guidance", json=payload, headers=headers)
    return response, mocked


def test_free_pro_and_vip_guidance_contracts(monkeypatch):
    free_response, free_mock = _request_guidance(monkeypatch, PAYLOAD, _headers())

    assert free_response.status_code == 200
    free_body = free_response.json()
    assert free_body["status"] == "success"
    assert free_body["membership"]["tier"] == "free"
    assert free_body["membership"]["is_subscriber"] is False
    assert free_body["membership"]["label"] == "免费版"
    assert free_body["membership"]["access"] == "foundation"
    assert free_body["data"] == {
        "core_energy": "核心能量",
        "career_guidance": "事业指引",
        "relationship_advice": "关系建议",
    }
    assert free_body["membership"]["unlocked_fields"] == [
        "core_energy",
        "career_guidance",
        "relationship_advice",
    ]
    assert free_body["membership"]["locked_fields"] == [
        "wealth_flow",
        "action_tips",
        "lucky_elements",
    ]
    assert set(free_body["membership"]["unlocked_fields"] + free_body["membership"]["locked_fields"]) == set(SIX_FIELDS)
    assert free_mock.call_args.kwargs["depth"] == "foundation"
    with database.SessionLocal() as session:
        stored = session.get(database.ReadingHistory, free_body["reading_id"])
    assert stored.core_energy == "核心能量"
    assert stored.career_guidance == "事业指引"
    assert stored.relationship_advice == "关系建议"
    assert stored.wealth_flow == ""
    assert stored.action_tips == ""
    assert stored.lucky_elements == ""

    locked_history = client.get(
        "/api/energy-history",
        params={"user_token": free_body["user_token"]},
        headers=_headers(),
    )
    assert locked_history.status_code == 403
    assert locked_history.json()["detail"]["code"] == "history_locked"

    token = free_body["user_token"]
    user_id = free_body["user_id"]
    database.set_membership(tier="one_time_pro", user_id=user_id)
    pro_response, pro_mock = _request_guidance(
        monkeypatch,
        {**PAYLOAD, "user_token": token},
        _headers(),
    )

    assert pro_response.status_code == 200
    pro_body = pro_response.json()
    assert pro_body["data"] == FULL_GUIDANCE
    assert list(pro_body["data"]) == list(SIX_FIELDS)
    assert pro_body["membership"] == {
        "tier": "one_time_pro",
        "is_subscriber": False,
        "label": "单次深度破局报告",
        "access": "full_coaching",
        "unlocked_fields": list(SIX_FIELDS),
        "locked_fields": [],
        "history_unlocked": False,
        "message": "单次深度破局报告已开通，财富行动、破局锦囊和每日幸运指引已打开。状态复盘属于月度或年度守护。",
    }
    assert pro_mock.call_args.kwargs["depth"] == "full_coaching"
    one_time_history = client.get(
        "/api/energy-history",
        params={"user_token": token},
        headers=_headers(),
    )
    assert one_time_history.status_code == 403

    database.set_membership(tier="yearly_subscriber", user_token=token)
    vip_response, vip_mock = _request_guidance(
        monkeypatch,
        PAYLOAD,
        _headers(**{"X-User-Token": token}),
    )

    assert vip_response.status_code == 200
    vip_body = vip_response.json()
    assert vip_body["user_id"] == user_id
    assert vip_body["data"] == FULL_GUIDANCE
    for field in SIX_FIELDS:
        assert vip_body["data"][field]
    assert vip_body["membership"]["tier"] == "yearly_subscriber"
    assert vip_body["membership"]["is_subscriber"] is True
    assert vip_body["membership"]["label"] == "年度能量守护"
    assert vip_body["membership"]["access"] == "full_coaching"
    assert vip_body["membership"]["locked_fields"] == []
    assert vip_body["membership"]["history_unlocked"] is True
    assert "年度能量守护" in vip_body["membership"]["message"]
    assert vip_mock.call_args.kwargs["depth"] == "full_coaching"

    history = client.get(
        "/api/energy-history",
        params={"user_token": token},
        headers=_headers(**{"X-User-Token": token}),
    )
    assert history.status_code == 200
    archive = history.json()
    assert archive["status"] == "success"
    assert archive["user"]["membership_tier"] == "yearly_subscriber"
    assert archive["user"]["is_subscriber"] is True
    assert archive["membership"]["access"] == "full_coaching"
    assert len(archive["data"]) == 3
    for premium_reading in archive["data"][:2]:
        for field in SIX_FIELDS:
            assert premium_reading[field]
    assert archive["data"][2]["core_energy"] == "核心能量"
    assert archive["data"][2]["career_guidance"] == "事业指引"
    assert archive["data"][2]["relationship_advice"] == "关系建议"
    assert "wealth_flow" not in archive["data"][2]
    assert "lucky_elements" not in archive["data"][2]

    database.set_membership(tier="free", user_id=user_id)
    downgraded = client.get(
        "/api/energy-history",
        params={"user_id": user_id},
        headers=_headers(),
    )
    assert downgraded.status_code == 403
    assert downgraded.json()["detail"]["code"] == "history_locked"
    assert "财富能量" not in downgraded.text


def test_expired_subscription_downgrades_to_free_and_locks_premium(monkeypatch):
    created, _ = _request_guidance(monkeypatch, PAYLOAD, _headers())
    assert created.status_code == 200
    created_body = created.json()
    token = created_body["user_token"]
    user_id = created_body["user_id"]

    database.set_membership(tier="yearly_subscriber", user_token=token)
    premium, premium_mock = _request_guidance(
        monkeypatch,
        {**PAYLOAD, "user_token": token},
        _headers(**{"X-User-Token": token}),
    )
    assert premium.status_code == 200
    assert premium.json()["membership"]["tier"] == "yearly_subscriber"
    assert premium.json()["membership"]["expires_at"]
    assert premium.json()["data"]["wealth_flow"] == "财富能量"
    assert premium_mock.call_args.kwargs["depth"] == "full_coaching"

    with database.SessionLocal() as session:
        user = session.get(database.User, user_id)
        user.expires_at = datetime.utcnow() - timedelta(days=1)
        session.commit()

    expired, expired_mock = _request_guidance(
        monkeypatch,
        {**PAYLOAD, "user_token": token},
        _headers(**{"X-User-Token": token}),
    )
    assert expired.status_code == 200
    expired_body = expired.json()
    assert expired_body["membership"]["tier"] == "free"
    assert expired_body["membership"]["is_subscriber"] is False
    assert expired_body["membership"]["access"] == "foundation"
    assert expired_body["membership"]["history_unlocked"] is False
    assert expired_body["membership"]["expires_at"]
    assert "已过期" in expired_body["membership"]["message"]
    assert expired_body["data"] == {
        "core_energy": "核心能量",
        "career_guidance": "事业指引",
        "relationship_advice": "关系建议",
    }
    assert expired_mock.call_args.kwargs["depth"] == "foundation"

    history = client.get(
        "/api/energy-history",
        params={"user_token": token},
        headers=_headers(**{"X-User-Token": token}),
    )
    assert history.status_code == 403
    detail = history.json()["detail"]
    assert detail["code"] == "history_locked"
    assert detail["tier"] == "free"
    assert "已过期" in detail["message"]
    assert "财富能量" not in history.text

    with database.SessionLocal() as session:
        user = session.get(database.User, user_id)
        assert user.membership_tier == "free"
        assert user.is_subscriber is False
        assert user.expires_at is not None


def test_deep_report_is_blocked_until_a_credit_is_bought_and_then_consumed(monkeypatch):
    created, _ = _request_guidance(monkeypatch, PAYLOAD, _headers())
    token = created.json()["user_token"]
    report_payload = {**PAYLOAD, "user_token": token, "question": "事业怎么破局"}

    blocked = client.post("/api/deep-report", json=report_payload, headers=_headers())
    assert blocked.status_code == 403
    detail = blocked.json()["detail"]
    assert detail["code"] == "deep_report_locked"
    assert detail["one_time_credits"] == 0
    assert "额度" in detail["message"]

    bought = client.post(
        "/api/mock-buy-deep-credit",
        json={"user_token": token, "quantity": 1},
        headers=_headers(),
    )
    assert bought.status_code == 200
    assert bought.json()["one_time_credits"] == 1
    assert bought.json()["membership"]["tier"] == "free"

    opened = client.post("/api/deep-report", json=report_payload, headers=_headers())
    assert opened.status_code == 200
    body = opened.json()
    assert body["product"] == "deep_bazi"
    assert body["access_via"] == "credit"
    assert body["one_time_credits"] == 0
    assert body["chart"]["pillars"]["day"]["gan_zhi"] == "庚辰"
    assert body["chart"]["pillars"]["day"]["shi_shen"] == "日主"
    assert body["chart"]["strength"]["label"] in {"身旺", "身弱", "中和"}
    assert [item["title"] for item in body["chapters"]] == ["性格底色", "财富格局", "事业破局", "流年大运"]
    assert "庚辰" in body["chapters"][0]["body"]
    assert "正官" in body["chapters"][2]["body"]

    spent = client.post("/api/deep-report", json=report_payload, headers=_headers())
    assert spent.status_code == 403
    assert spent.json()["detail"]["one_time_credits"] == 0

    database.set_membership(tier="yearly_subscriber", user_token=token)
    database.grant_deep_credits(quantity=2, user_token=token)
    privileged = client.post("/api/deep-report", json=report_payload, headers=_headers())
    assert privileged.status_code == 200
    assert privileged.json()["access_via"] == "subscription"
    assert privileged.json()["one_time_credits"] == 2
