"""Instant 履约：校验、空盘、幂等、限流、错误文案和日志脱敏。"""

import logging
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import bazi
import database
import fulfillment
import main

client = TestClient(main.app)

PAYLOAD = {
    "birth_date": "1990-01-15",
    "birth_time": "08:30",
    "gender": "female",
    "question": "今日能量指引",
}

MOCK = {
    "core_energy": "核心能量",
    "career_guidance": "事业指引",
    "relationship_advice": "关系建议",
    "wealth_flow": "财富能量",
    "action_tips": "行动锦囊",
    "lucky_elements": "幸运密码",
}


def _headers(**extra):
    return {"X-API-Key": "test-secret", **extra}


def _user_count() -> int:
    with database.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(database.User))


def _reading_count() -> int:
    with database.SessionLocal() as session:
        return session.scalar(select(func.count()).select_from(database.ReadingHistory))


def _credits(token: str) -> int:
    with database.SessionLocal() as session:
        user = session.scalar(select(database.User).where(database.User.token == token))
        return int(user.one_time_credits or 0)


def _ledger(token: str) -> list:
    with database.SessionLocal() as session:
        user = session.scalar(select(database.User).where(database.User.token == token))
        rows = session.scalars(
            select(database.DeepReportLedger)
            .where(database.DeepReportLedger.user_id == user.id)
            .order_by(database.DeepReportLedger.id)
        ).all()
        return [row.event_type for row in rows]


def _member(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)):
        created = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())
    assert created.status_code == 200
    return created.json()


def test_locale_negotiation_ignores_broken_headers():
    assert fulfillment.negotiate_locale(None) == "zh"
    assert fulfillment.negotiate_locale("") == "zh"
    assert fulfillment.negotiate_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh"
    assert fulfillment.negotiate_locale("zh-TW,en;q=0.4") == "zh"
    assert fulfillment.negotiate_locale("en-US,en;q=0.9,zh;q=0.8") == "en"
    assert fulfillment.negotiate_locale("en;q=0,zh;q=0.2") == "zh"
    assert fulfillment.negotiate_locale("en;q=abc") == "zh"
    assert fulfillment.negotiate_locale("fr, de") == "zh"
    assert fulfillment.negotiate_locale("*") == "zh"
    assert fulfillment.negotiate_locale("x" * 500) == "zh"
    assert "sk-supersecretkeyvalue" not in fulfillment.scrub("token=sk-supersecretkeyvalue bearer abc.def")
    assert fulfillment.redact_birth_date("1990-01-15") == "1990-01-**"


def test_invalid_birth_data_never_calls_the_model(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        missing = client.post(
            "/api/energy-guidance",
            json={**PAYLOAD, "birth_date": "1990-02-31"},
            headers=_headers(),
        )
        huge = client.post(
            "/api/energy-guidance",
            json={**PAYLOAD, "question": "问" * 2001},
            headers=_headers(),
        )
        normalized = client.post(
            "/api/energy-guidance",
            json={**PAYLOAD, "birth_date": "1990-1-5", "birth_time": "8:05", "question": "今日\x00能量"},
            headers=_headers(),
        )

    assert missing.status_code == 400
    assert missing.json()["detail"] == "出生日期需要是 YYYY-MM-DD"
    assert huge.status_code == 400
    assert "过长" in huge.json()["detail"]
    assert normalized.status_code == 200
    assert mocked.call_count == 1
    assert mocked.call_args.kwargs["birth_date"] == "1990-01-05"
    assert mocked.call_args.kwargs["birth_time"] == "08:05"
    assert mocked.call_args.kwargs["question"] == "今日能量"
    assert _user_count() == 1

    english = client.post(
        "/api/energy-guidance",
        json={**PAYLOAD, "birth_time": "25:99"},
        headers=_headers(**{"Accept-Language": "en-GB,en;q=0.8"}),
    )
    assert english.status_code == 400
    assert english.json()["detail"] == "Birth time must be HH:MM."


def test_failed_and_empty_guidance_do_not_persist_or_leak(monkeypatch, caplog):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    engine_log = logging.getLogger("astrology_engine")
    engine_log.addHandler(caplog.handler)
    engine_log.setLevel(logging.INFO)
    try:
        with patch.object(
            main,
            "get_astrology_energy_guidance",
            side_effect=RuntimeError("model down sk-supersecretkeyvalue"),
        ):
            failed = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())
        assert failed.status_code == 500
        assert failed.json()["detail"]["code"] == "internal"
        assert "sk-" not in failed.text
        assert "model down" not in failed.text
        assert "sk-" not in caplog.text

        empty = dict(MOCK)
        empty["core_energy"] = "   "
        with patch.object(main, "get_astrology_energy_guidance", return_value=empty):
            blank = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())
        assert blank.status_code == 502
        assert blank.json()["detail"]["code"] == "model_output"
        assert _user_count() == 0
    finally:
        engine_log.removeHandler(caplog.handler)


def test_upstream_rate_limit_is_visible_and_not_stored(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(
        main,
        "get_astrology_energy_guidance",
        side_effect=main.GuidanceRateLimited(4),
    ) as mocked:
        response = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "model_rate_limited"
    assert response.headers["retry-after"] == "4"
    assert mocked.call_count == 1
    assert _user_count() == 0

    with patch.object(
        main,
        "get_astrology_energy_guidance",
        side_effect=main.GuidanceUnavailable("APITimeoutError"),
    ):
        unavailable = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "model_unavailable"


def test_idempotent_energy_replay_does_not_call_the_model_twice(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    headers = _headers(**{"Idempotency-Key": "energy-retry-0001"})
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        first = client.post("/api/energy-guidance", json=PAYLOAD, headers=headers)
        second = client.post("/api/energy-guidance", json=PAYLOAD, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["idempotency-replay"] == "true"
    assert second.json()["reading_id"] == first.json()["reading_id"]
    assert second.json()["user_token"] == first.json()["user_token"]
    assert mocked.call_count == 1
    assert _reading_count() == 1

    changed = dict(PAYLOAD)
    changed["question"] = "另一件事"
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        conflict = client.post("/api/energy-guidance", json=changed, headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "幂等键与请求内容不一致"
    assert mocked.call_count == 0
    assert _reading_count() == 1


def test_failed_idempotent_energy_can_be_retried(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    headers = _headers(**{"Idempotency-Key": "energy-retry-0002"})
    with patch.object(main, "get_astrology_energy_guidance", side_effect=RuntimeError("down")):
        failed = client.post("/api/energy-guidance", json=PAYLOAD, headers=headers)
    assert failed.status_code == 500
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        recovered = client.post("/api/energy-guidance", json=PAYLOAD, headers=headers)
    assert recovered.status_code == 200
    assert mocked.call_count == 1
    assert _reading_count() == 1


def test_short_idempotency_key_is_rejected(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        response = client.post(
            "/api/energy-guidance",
            json=PAYLOAD,
            headers=_headers(**{"Idempotency-Key": "short-key"}),
        )
    assert response.status_code == 400
    assert mocked.call_count == 0


def test_inbound_rate_limit_stops_before_the_model(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    monkeypatch.setenv("INSTANT_RATE_LIMIT_PER_MINUTE", "2")
    fulfillment.reset_rate_limiter()
    with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)) as mocked:
        statuses = [
            client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers()).status_code
            for _ in range(3)
        ]
        limited = client.post(
            "/api/energy-guidance",
            json=PAYLOAD,
            headers=_headers(**{"Accept-Language": "en"}),
        )
    assert statuses == [200, 200, 429]
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert limited.json()["detail"]["message"] == "Too many requests. Please retry shortly."
    assert limited.headers["retry-after"]
    assert mocked.call_count == 2


def test_request_id_is_echoed_or_replaced():
    echoed = client.get("/", headers={"Accept": "application/json", "X-Request-Id": "req-1234abcd"})
    assert echoed.status_code == 200
    assert echoed.headers["x-request-id"] == "req-1234abcd"
    replaced = client.get("/", headers={"Accept": "application/json", "X-Request-Id": "bad id"})
    assert replaced.headers["x-request-id"] != "bad id"
    assert len(replaced.headers["x-request-id"]) >= 8


def test_localized_auth_and_history_errors(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    chinese = client.post("/api/energy-guidance", json=PAYLOAD, headers={"Accept-Language": ";;;"})
    assert chinese.status_code == 401
    assert chinese.json()["detail"] == "未授权"
    english = client.post(
        "/api/energy-guidance",
        json=PAYLOAD,
        headers={"Accept-Language": "en-US,en;q=0.9,zh;q=0.1"},
    )
    assert english.status_code == 401
    assert english.json()["detail"] == "Unauthorized"

    created = _member(monkeypatch)
    locked = client.get(
        "/api/energy-history",
        params={"user_token": created["user_token"]},
        headers=_headers(**{"Accept-Language": "en"}),
    )
    assert locked.status_code == 403
    assert locked.json()["detail"]["code"] == "history_locked"
    assert "History belongs" in locked.json()["detail"]["message"]


def test_success_log_does_not_include_token_or_full_birth_day(monkeypatch, caplog):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")
    log = logging.getLogger("fulfillment")
    log.addHandler(caplog.handler)
    log.setLevel(logging.INFO)
    try:
        with patch.object(main, "get_astrology_energy_guidance", return_value=dict(MOCK)):
            response = client.post("/api/energy-guidance", json=PAYLOAD, headers=_headers())
        token = response.json()["user_token"]
        assert token not in caplog.text
        assert "test-secret" not in caplog.text
        assert "1990-01-15" not in caplog.text
        assert "1990-01-**" in caplog.text
        assert "request_succeeded" in caplog.text
    finally:
        log.removeHandler(caplog.handler)


def test_empty_chart_does_not_spend_a_credit(monkeypatch):
    created = _member(monkeypatch)
    token = created["user_token"]
    database.grant_deep_credits(quantity=1, user_token=token)
    original = bazi.cast_chart

    def blank(*args, **kwargs):
        chart = original(*args, **kwargs)
        chart["pillars"]["day"]["gan_zhi"] = ""
        return chart

    monkeypatch.setattr(bazi, "cast_chart", blank)
    response = client.post(
        "/api/deep-report",
        json={**PAYLOAD, "user_token": token},
        headers=_headers(**{"Accept-Language": "en"}),
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The chart came back incomplete."
    assert _credits(token) == 1
    assert _ledger(token) == ["grant"]


def test_credit_is_refunded_when_response_fails_after_charge(monkeypatch):
    created = _member(monkeypatch)
    token = created["user_token"]
    database.grant_deep_credits(quantity=1, user_token=token)

    def boom(*args, **kwargs):
        raise RuntimeError("serialize failed sk-supersecretkeyvalue")

    monkeypatch.setattr(main, "DeepReportResponse", boom)
    response = client.post(
        "/api/deep-report",
        json={**PAYLOAD, "user_token": token, "question": "事业怎么破局"},
        headers=_headers(),
    )
    assert response.status_code == 500
    assert "sk-" not in response.text
    assert _credits(token) == 1
    assert _ledger(token) == ["grant", "consume", "refund"]


def test_subscription_failure_does_not_mint_a_credit(monkeypatch):
    created = _member(monkeypatch)
    token = created["user_token"]
    database.set_membership(tier="yearly_subscriber", user_token=token)
    database.grant_deep_credits(quantity=2, user_token=token)

    def boom(*args, **kwargs):
        raise RuntimeError("serialize failed")

    monkeypatch.setattr(main, "DeepReportResponse", boom)
    response = client.post(
        "/api/deep-report",
        json={**PAYLOAD, "user_token": token},
        headers=_headers(),
    )
    assert response.status_code == 500
    assert _credits(token) == 2
    assert "refund" not in _ledger(token)
    assert "subscription_pass" in _ledger(token)


def test_deep_report_idempotency_spends_one_credit(monkeypatch):
    created = _member(monkeypatch)
    token = created["user_token"]
    database.grant_deep_credits(quantity=1, user_token=token)
    calls = {"n": 0}
    real = main.compose_deep_report

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(main, "compose_deep_report", wrapped)
    body = {**PAYLOAD, "user_token": token, "birth_city": "乌鲁木齐", "question": "事业怎么破局"}
    headers = _headers(**{"Idempotency-Key": "deep-report-key-01"})
    first = client.post("/api/deep-report", json=body, headers=headers)
    second = client.post("/api/deep-report", json=body, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["idempotency-replay"] == "true"
    assert second.json()["one_time_credits"] == 0
    assert second.json()["chart"]["birth_city"] == "乌鲁木齐"
    assert calls["n"] == 1
    assert _credits(token) == 0

    other = dict(body)
    other["question"] = "另一件事"
    conflict = client.post("/api/deep-report", json=other, headers=headers)
    assert conflict.status_code == 409
    assert calls["n"] == 1
    assert _credits(token) == 0


def test_idempotency_pending_can_be_taken_over_after_it_goes_stale():
    scope = "energy-guidance:user:1"
    key = "energy-retry-0099"
    database.claim_idempotency(scope=scope, idempotency_key=key, request_hash="a" * 64)
    with pytest.raises(database.IdempotencyInProgress):
        database.claim_idempotency(scope=scope, idempotency_key=key, request_hash="a" * 64)
    with database.SessionLocal() as session:
        row = session.scalar(select(database.IdempotencyRecord))
        row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        session.commit()
    assert database.claim_idempotency(scope=scope, idempotency_key=key, request_hash="a" * 64) is None
    database.complete_idempotency(scope=scope, idempotency_key=key, status_code=200, body={"status": "success"})
    replay = database.claim_idempotency(scope=scope, idempotency_key=key, request_hash="a" * 64)
    assert replay["body"]["status"] == "success"
    with pytest.raises(database.IdempotencyConflict):
        database.claim_idempotency(scope=scope, idempotency_key=key, request_hash="b" * 64)


def test_deep_report_still_rejects_unknown_city_before_charging(monkeypatch):
    created = _member(monkeypatch)
    token = created["user_token"]
    database.grant_deep_credits(quantity=1, user_token=token)
    response = client.post(
        "/api/deep-report",
        json={**PAYLOAD, "user_token": token, "birth_city": "不存在的城市"},
        headers=_headers(),
    )
    assert response.status_code == 400
    assert "经度" in response.json()["detail"]
    assert _credits(token) == 1
