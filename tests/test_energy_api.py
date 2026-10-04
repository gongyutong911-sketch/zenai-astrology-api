import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from unittest.mock import patch

from fastapi.testclient import TestClient

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
    assert "开始解读" in response.text
    assert "核心能量" in response.text


def test_browser_root_returns_page():
    response = client.get("/", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert "开始解读" in response.text


def test_energy_guidance_requires_api_key(monkeypatch):
    monkeypatch.setenv("API_SECRET_KEY", "test-secret")

    response = client.post("/api/energy-guidance", json=ENERGY_PAYLOAD)

    assert response.status_code == 401
    assert response.json() == {"detail": "未授权"}


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
            headers={"X-API-Key": "test-secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "success", "data": MOCK_GUIDANCE}
    mock_guidance.assert_called_once_with(
        birth_date="1990-01-15",
        birth_time="08:30",
        gender="female",
        question="今日能量指引",
    )
