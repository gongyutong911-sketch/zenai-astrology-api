"""Instant 模型调用：只重试可恢复错误，限流和密钥隔离不跟着重试。"""

import json
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ["DATABASE_URL"] = "sqlite://"

import httpx2
import pytest
from openai import APITimeoutError, InternalServerError, RateLimitError
from tenacity import wait_none

import astrology_engine

MOCK = {
    "core_energy": "核心能量",
    "career_guidance": "事业指引",
    "relationship_advice": "关系建议",
    "wealth_flow": "财富能量",
    "action_tips": "行动锦囊",
    "lucky_elements": "幸运密码",
}


def _request():
    return httpx2.Request("POST", "https://example.invalid/v1/chat/completions")


def _response(status, headers=None):
    return httpx2.Response(status, headers=headers or {}, request=_request())


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Completion:
    def __init__(self, content):
        self.choices = [_Choice(content)]


def _install(monkeypatch, create):
    monkeypatch.setattr(astrology_engine._complete_guidance.retry, "wait", wait_none())

    class _Completions:
        def create(self, **kwargs):
            return create(**kwargs)

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    monkeypatch.setattr(astrology_engine, "_openai_client", lambda: _Client())


def test_client_uses_only_the_instant_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "instant-key")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "bot-admin-secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    astrology_engine._reset_client_cache()

    client = astrology_engine._openai_client()

    assert client.api_key == "instant-key"
    assert client.admin_api_key != "bot-admin-secret"
    assert client.admin_api_key in ("", None)
    assert client.max_retries == 0
    assert "deepseek.com" in str(client.base_url)
    astrology_engine._reset_client_cache()


def test_missing_instant_key_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "bot-admin-secret")
    astrology_engine._reset_client_cache()

    with pytest.raises(astrology_engine.GuidanceUnavailable) as caught:
        astrology_engine._openai_client()

    assert caught.value.reason == "missing_api_key"
    astrology_engine._reset_client_cache()


def test_timeout_then_success_retries_without_sleeping_the_suite(monkeypatch):
    calls = {"n": 0}

    def create(**kwargs):
        calls["n"] += 1
        assert kwargs["model"] == "deepseek-flash"
        if calls["n"] < 3:
            raise APITimeoutError(_request())
        return _Completion(json.dumps(MOCK))

    _install(monkeypatch, create)
    parsed = astrology_engine.get_astrology_energy_guidance("1990-01-15", "08:30", "female", "今日", "foundation")

    assert calls["n"] == 3
    assert parsed["core_energy"] == "核心能量"
    assert "wealth_flow" not in parsed


def test_server_error_retries_and_rate_limit_does_not(monkeypatch):
    calls = {"n": 0}

    def create(**kwargs):
        calls["n"] += 1
        raise InternalServerError("upstream", response=_response(500), body=None)

    _install(monkeypatch, create)
    with pytest.raises(InternalServerError):
        astrology_engine.get_astrology_energy_guidance("1990-01-15")
    assert calls["n"] == 3

    calls["n"] = 0

    def limited(**kwargs):
        calls["n"] += 1
        raise RateLimitError(
            "slow down sk-supersecretkeyvalue",
            response=_response(429, {"retry-after": "4"}),
            body={"error": {"message": "sk-supersecretkeyvalue"}},
        )

    _install(monkeypatch, limited)
    with pytest.raises(astrology_engine.GuidanceRateLimited) as caught:
        astrology_engine.get_astrology_energy_guidance("1990-01-15")
    assert calls["n"] == 1
    assert caught.value.retry_after == 4


def test_empty_and_broken_json_are_retried(monkeypatch):
    calls = {"n": 0}

    def empty(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Completion("  ")
        if calls["n"] == 2:
            return _Completion("not-json")
        return _Completion(json.dumps({"core_energy": "  "}))

    _install(monkeypatch, empty)
    with pytest.raises(astrology_engine.GuidanceOutputError):
        astrology_engine.get_astrology_energy_guidance("1990-01-15", depth="foundation")
    assert calls["n"] == 3


def test_bad_depth_does_not_call_the_model(monkeypatch):
    def create(**kwargs):
        raise AssertionError("model should not be called")

    _install(monkeypatch, create)
    with pytest.raises(ValueError, match="解读深度"):
        astrology_engine.get_astrology_energy_guidance("1990-01-15", depth="nope")
