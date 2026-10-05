import json
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import astrology_engine
import database
import main

client = TestClient(main.app)

ENERGY_PAYLOAD = {
    "birth_date": "1990-01-15",
    "birth_time": "08:30",
    "gender": "female",
    "question": "今日能量指引",
}

MOCK_GUIDANCE = {
    "core_energy": "核心能量",
    "career_guidance": "事业指引",
    "relationship_advice": "关系建议",
    "wealth_flow": "财富能量",
    "action_tips": "行动锦囊",
    "lucky_elements": "幸运密码",
}


def test_health_check_returns_ok():
    response = client.get("/", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": "ZenAI Astrology & Energy API is running smoothly!",
    }


def test_ui_page_is_served():
    response = client.get("/ui")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "开始觉察" in response.text
    assert "核心能量" in response.text
    assert "财富行动" in response.text
    assert "破局锦囊" in response.text
    assert "每日幸运指引" in response.text
    assert "单次深度破局报告" in response.text
    assert "月度能量守护 VIP" in response.text
    assert "年度能量守护 VIP" in response.text
    assert "/api/mock-checkout" in response.text
    assert "/api/deep-report" in response.text
    assert "人生战略与财富矩阵深度排盘" in response.text
    assert "模拟购买 1 次额度" in response.text
    assert "¥68" in response.text
    assert "出生经度" in response.text
    assert "乌鲁木齐" in response.text
    assert "早子时" in response.text
    assert "晚子时" in response.text


def test_browser_root_returns_page():
    response = client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert "开始觉察" in response.text


def test_energy_guidance_requires_api_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    response = client.post("/api/energy-guidance", json=ENERGY_PAYLOAD)

    assert response.status_code == 401
    assert response.json() == {"detail": "未授权"}


def _auth_headers():
    return {"X-API-Key": "test-secret"}


def _user_count() -> int:
    with database.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(database.User))


def test_energy_guidance_with_valid_api_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    with patch.object(
        main,
        "get_astrology_energy_guidance",
        return_value=MOCK_GUIDANCE,
    ) as mock_guidance:
        response = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"] == {
        "core_energy": "核心能量",
        "career_guidance": "事业指引",
        "relationship_advice": "关系建议",
    }
    assert body["membership"]["tier"] == "free"
    assert body["membership"]["is_subscriber"] is False
    assert body["membership"]["label"] == "免费版"
    assert body["membership"]["access"] == "foundation"
    assert body["membership"]["locked_fields"] == [
        "wealth_flow",
        "action_tips",
        "lucky_elements",
    ]
    assert "免费版" in body["membership"]["message"]
    assert isinstance(body["user_id"], int)
    assert body["user_token"]
    assert isinstance(body["reading_id"], int)
    mock_guidance.assert_called_once_with(
        birth_date="1990-01-15",
        birth_time="08:30",
        gender="female",
        question="今日能量指引",
        depth="foundation",
    )

    history = client.get(
        "/api/energy-history",
        params={"user_token": body["user_token"]},
        headers=_auth_headers(),
    )
    assert history.status_code == 403
    assert history.json()["detail"]["code"] == "history_locked"
    with database.SessionLocal() as session:
        stored = session.get(database.ReadingHistory, body["reading_id"])
    assert stored.core_energy == "核心能量"
    assert stored.career_guidance == "事业指引"
    assert stored.relationship_advice == "关系建议"
    assert stored.wealth_flow == ""
    assert stored.action_tips == ""
    assert stored.lucky_elements == ""


def test_rejected_request_does_not_write_history(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    response = client.post("/api/energy-guidance", json=ENERGY_PAYLOAD)

    assert response.status_code == 401
    assert _user_count() == 0


def test_failed_guidance_does_not_write_history(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    with patch.object(
        main,
        "get_astrology_energy_guidance",
        side_effect=RuntimeError("model down"),
    ):
        response = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )

    assert response.status_code == 500
    assert _user_count() == 0


def test_history_appends_for_the_same_user_and_can_be_queried_by_id(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    later = dict(MOCK_GUIDANCE)
    later["core_energy"] = "第二次核心能量"
    later["wealth_flow"] = "第二次财富能量"

    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        first = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )
    assert first.status_code == 200
    identity = first.json()
    database.set_membership(tier="monthly_subscriber", user_id=identity["user_id"])

    follow_up = dict(ENERGY_PAYLOAD)
    follow_up["question"] = "下周财运"
    follow_up["birth_date"] = "1991-02-02"
    follow_up["user_token"] = identity["user_token"]
    with patch.object(main, "get_astrology_energy_guidance", return_value=later):
        second = client.post(
            "/api/energy-guidance",
            json=follow_up,
            headers=_auth_headers(),
        )
    assert second.status_code == 200
    assert second.json()["user_id"] == identity["user_id"]
    assert second.json()["user_token"] == identity["user_token"]
    assert second.json()["data"]["wealth_flow"] == "第二次财富能量"
    assert second.json()["membership"]["tier"] == "monthly_subscriber"
    assert second.json()["membership"]["is_subscriber"] is True
    assert second.json()["membership"]["access"] == "full_coaching"
    assert second.json()["membership"]["locked_fields"] == []

    history = client.get(
        "/api/energy-history",
        params={"user_id": identity["user_id"]},
        headers=_auth_headers(),
    )
    assert history.status_code == 200
    archive = history.json()
    assert archive["user"]["birth_date"] == "1991-02-02"
    assert archive["membership"]["tier"] == "monthly_subscriber"
    assert [item["question"] for item in archive["data"]] == ["下周财运", "今日能量指引"]
    assert archive["data"][0]["wealth_flow"] == "第二次财富能量"
    assert archive["data"][1]["birth_date"] == "1990-01-15"
    assert "wealth_flow" not in archive["data"][1]
    assert archive["data"][0]["birth_date"] == "1991-02-02"
    assert _user_count() == 1


def test_history_requires_api_key_and_known_identity(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    missing_key = client.get("/api/energy-history", params={"user_id": 1})
    assert missing_key.status_code == 401
    assert missing_key.json() == {"detail": "未授权"}

    missing_identity = client.get("/api/energy-history", headers=_auth_headers())
    assert missing_identity.status_code == 400

    unknown = client.get(
        "/api/energy-history",
        params={"user_token": "missing-token"},
        headers=_auth_headers(),
    )
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "未找到对应用户"}


def test_mismatched_user_id_and_token_is_rejected(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        first = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )
        second = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )
    assert first.status_code == 200
    assert second.status_code == 200

    mixed = dict(ENERGY_PAYLOAD)
    mixed["user_id"] = first.json()["user_id"]
    mixed["user_token"] = second.json()["user_token"]
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        response = client.post(
            "/api/energy-guidance",
            json=mixed,
            headers=_auth_headers(),
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "用户标识不一致"}
    with database.SessionLocal() as session:
        readings = session.scalar(select(func.count()).select_from(database.ReadingHistory))
    assert readings == 2


def test_remember_reading_roundtrip():
    saved = database.remember_reading(
        birth_date="1988-08-08",
        birth_time="09:15",
        gender="male",
        question="事业",
        guidance=MOCK_GUIDANCE,
    )
    archive = database.list_readings(user_id=saved["user"]["id"])

    assert archive["user"]["token"] == saved["user"]["token"]
    assert archive["user"]["gender"] == "male"
    assert archive["user"]["membership_tier"] == "free"
    assert archive["user"]["is_subscriber"] is False
    assert archive["readings"][0]["question"] == "事业"
    assert archive["readings"][0]["lucky_elements"] == "幸运密码"
    again = database.list_readings(user_token=saved["user"]["token"])
    assert again["readings"][0]["id"] == saved["reading"]["id"]


def test_parse_guidance_includes_new_dimensions():
    parsed = astrology_engine._parse_guidance(json.dumps(MOCK_GUIDANCE))

    assert parsed == MOCK_GUIDANCE
    incomplete = dict(MOCK_GUIDANCE)
    incomplete.pop("wealth_flow")
    incomplete.pop("action_tips")
    incomplete.pop("lucky_elements")
    with pytest.raises(ValueError, match="wealth_flow"):
        astrology_engine._parse_guidance(json.dumps(incomplete))


def test_daily_prompt_asks_only_for_the_shallow_sign():
    messages = astrology_engine._guidance_messages(
        "1990-01-15",
        "08:30",
        "female",
        "今日能量指引",
        astrology_engine.DEPTH_DAILY,
    )
    prompt = messages[1]["content"]
    assert "现代心理能量教练" in messages[0]["content"]
    assert "能量状态诊断" in prompt
    assert "绝对化断言" in messages[0]["content"]
    assert "封建迷信" in messages[0]["content"]
    assert "core_energy" in prompt
    assert "career_guidance" in prompt
    assert "relationship_advice" in prompt
    assert "wealth_flow" not in prompt
    coaching = astrology_engine._guidance_messages(
        "1990-01-15",
        "08:30",
        "female",
        "今日能量指引",
        astrology_engine.DEPTH_COACHING,
    )
    assert "现代心理能量教练" in coaching[0]["content"]
    assert "Pro 进阶版行动方案" in coaching[1]["content"]
    assert "不要预言财运" in coaching[1]["content"]
    assert "wealth_flow" in coaching[1]["content"]
    daily = astrology_engine._parse_guidance(
        json.dumps({**MOCK_GUIDANCE, "wealth_flow": "不应保留"}),
        astrology_engine.FREE_FIELDS,
    )
    assert daily == {
        "core_energy": "核心能量",
        "career_guidance": "事业指引",
        "relationship_advice": "关系建议",
    }
    assert database.DAILY_SIGN_FIELDS == astrology_engine.DAILY_SIGN_FIELDS


def test_vip_header_unlocks_full_coaching(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        created = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )
    assert created.status_code == 200
    token = created.json()["user_token"]
    database.set_membership(tier="yearly_subscriber", user_token=token)

    with patch.object(
        main,
        "get_astrology_energy_guidance",
        return_value=MOCK_GUIDANCE,
    ) as mock_guidance:
        response = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers={**_auth_headers(), "X-User-Token": token},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == MOCK_GUIDANCE
    assert body["membership"]["tier"] == "yearly_subscriber"
    assert body["membership"]["is_subscriber"] is True
    assert body["membership"]["label"] == "年度能量守护"
    assert body["membership"]["access"] == "full_coaching"
    assert body["membership"]["locked_fields"] == []
    assert body["membership"]["history_unlocked"] is True
    assert "年度能量守护" in body["membership"]["message"]
    mock_guidance.assert_called_once_with(
        birth_date="1990-01-15",
        birth_time="08:30",
        gender="female",
        question="今日能量指引",
        depth="full_coaching",
    )


def test_unknown_member_token_does_not_call_the_model(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE) as mock_guidance:
        response = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers={**_auth_headers(), "X-User-Token": "missing-token"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "未找到对应用户"}
    mock_guidance.assert_not_called()
    assert _user_count() == 0


def test_downgrade_hides_premium_history_until_restored(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        created = client.post(
            "/api/energy-guidance",
            json=ENERGY_PAYLOAD,
            headers=_auth_headers(),
        )
    token = created.json()["user_token"]
    user_id = created.json()["user_id"]
    database.set_membership(tier="yearly_subscriber", user_id=user_id)
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        premium = client.post(
            "/api/energy-guidance",
            json={**ENERGY_PAYLOAD, "user_token": token},
            headers=_auth_headers(),
        )
    assert premium.status_code == 200
    assert premium.json()["data"]["career_guidance"] == "事业指引"

    database.set_membership(tier="free", user_token=token)
    hidden = client.get(
        "/api/energy-history",
        params={"user_token": token},
        headers=_auth_headers(),
    )
    assert hidden.status_code == 403
    assert hidden.json()["detail"]["code"] == "history_locked"
    assert "career_guidance" not in hidden.text
    with database.SessionLocal() as session:
        stored = session.scalar(select(database.ReadingHistory).order_by(database.ReadingHistory.id.desc()))
    assert stored.career_guidance == "事业指引"

    database.set_membership(tier="one_time_pro", user_id=user_id)
    still_locked = client.get(
        "/api/energy-history",
        params={"user_id": user_id},
        headers=_auth_headers(),
    )
    assert still_locked.status_code == 403

    database.set_membership(tier="monthly_subscriber", user_id=user_id)
    restored = client.get(
        "/api/energy-history",
        params={"user_id": user_id},
        headers=_auth_headers(),
    )
    assert restored.json()["data"][0]["career_guidance"] == "事业指引"
    assert restored.json()["membership"]["is_subscriber"] is True


def test_set_membership_rejects_unknown_tier():
    saved = database.remember_reading(
        birth_date="1988-08-08",
        birth_time="09:15",
        gender="male",
        question="事业",
        guidance=MOCK_GUIDANCE,
    )
    with pytest.raises(database.InvalidMembership):
        database.set_membership(tier="gold", user_id=saved["user"]["id"])


def test_existing_sqlite_users_gain_membership_columns(tmp_path):
    from sqlalchemy import create_engine

    old = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                token VARCHAR(64) NOT NULL,
                birth_date VARCHAR(32) NOT NULL,
                birth_time VARCHAR(16) NOT NULL,
                gender VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO users (token, birth_date, birth_time, gender, created_at)
            VALUES ('tok', '1990-01-01', '12:00', 'female', '2026-01-01 00:00:00')
            """
        )
    database.ensure_membership_columns(old)
    database.ensure_membership_columns(old)
    with old.connect() as conn:
        names = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)")}
        row = conn.exec_driver_sql("SELECT membership_tier, is_subscriber FROM users").one()
    assert {"membership_tier", "is_subscriber"} <= names
    assert row[0] == "free"
    assert row[1] in (0, False)


def test_legacy_membership_tiers_are_remapped(tmp_path):
    from sqlalchemy import create_engine

    old = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with old.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                token VARCHAR(64) NOT NULL,
                birth_date VARCHAR(32) NOT NULL,
                birth_time VARCHAR(16) NOT NULL,
                gender VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL,
                membership_tier VARCHAR(32) NOT NULL DEFAULT 'free',
                is_subscriber BOOLEAN NOT NULL DEFAULT 0
            )
            """
        )
        conn.exec_driver_sql(
            """
            INSERT INTO users (token, birth_date, birth_time, gender, created_at, membership_tier, is_subscriber)
            VALUES
                ('pro', '1990-01-01', '12:00', 'female', '2026-01-01 00:00:00', 'pro_report', 0),
                ('vip', '1991-01-01', '12:00', 'male', '2026-01-01 00:00:00', 'vip_subscriber', 1)
            """
        )
    database.ensure_membership_columns(old)
    with old.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT token, membership_tier, is_subscriber FROM users ORDER BY token"
        ).all()
    assert rows[0][1] == "one_time_pro"
    assert rows[1][1] == "monthly_subscriber"
    assert rows[1][2] in (1, True)


def test_mock_checkout_opens_the_selected_plan(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=MOCK_GUIDANCE):
        created = client.post("/api/energy-guidance", json=ENERGY_PAYLOAD, headers=_auth_headers())
    token = created.json()["user_token"]

    missing = client.post("/api/mock-checkout", json={"plan_type": "monthly"})
    assert missing.status_code == 401

    unknown = client.post(
        "/api/mock-checkout",
        json={"plan_type": "monthly"},
        headers=_auth_headers(),
    )
    assert unknown.status_code == 404

    invalid = client.post(
        "/api/mock-checkout",
        json={"plan_type": "lifetime", "user_token": token},
        headers=_auth_headers(),
    )
    assert invalid.status_code == 400

    one_time = client.post(
        "/api/mock-checkout",
        json={"plan_type": "one_time", "user_token": token},
        headers=_auth_headers(),
    )
    assert one_time.status_code == 200
    assert one_time.json()["membership"]["tier"] == "one_time_pro"
    assert one_time.json()["membership"]["is_subscriber"] is False
    assert one_time.json()["membership"]["history_unlocked"] is False
    locked = client.get("/api/energy-history", params={"user_token": token}, headers=_auth_headers())
    assert locked.status_code == 403

    yearly = client.post(
        "/api/mock-checkout",
        json={"plan_type": "yearly", "user_token": token},
        headers=_auth_headers(),
    )
    assert yearly.status_code == 200
    assert yearly.json()["membership"]["tier"] == "yearly_subscriber"
    assert yearly.json()["membership"]["is_subscriber"] is True
    opened = client.get("/api/energy-history", params={"user_token": token}, headers=_auth_headers())
    assert opened.status_code == 200
