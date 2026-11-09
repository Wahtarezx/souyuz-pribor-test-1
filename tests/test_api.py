from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers import ProviderError
from app.schemas import GeneratedContent


def create(client, product):
    response = client.post("/api/drafts", json={"product": product, "provider": "manual"})
    assert response.status_code == 201
    return response.json()


def completion(draft, content):
    return {"draft_id": draft["id"], "input_hash": draft["input_hash"], "content": content}


def test_manual_round_trip_persists_and_exports(client, product, content):
    draft = create(client, product)
    assert draft["status"] == "pending"
    bundle = client.get(f"/api/drafts/{draft['id']}/request").json()
    assert bundle["input_hash"] == draft["input_hash"]
    assert bundle["response_schema"]["additionalProperties"] is False
    response = client.post(f"/api/drafts/{draft['id']}/result", json=completion(draft, content))
    assert response.status_code == 200
    saved = client.get(f"/api/drafts/{draft['id']}").json()
    assert saved["status"] == "completed"
    assert saved["result"]["seo_description"] == content["seo_description"]
    assert "диапазон измерений" in saved["result"]["missing_fields"]
    assert {"name": "артикул", "value": "0563 0510"} in saved["result"]["characteristics"]
    markdown = client.get(f"/api/drafts/{draft['id']}/markdown")
    assert markdown.status_code == 200
    assert "данных нет" in markdown.text
    assert "## Для менеджера" in markdown.text
    assert client.get("/api/drafts").json()[0]["id"] == draft["id"]


def test_database_survives_app_restart(tmp_path, product, content):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/persist.db", _env_file=None)
    with TestClient(create_app(settings)) as first:
        draft = create(first, product)
        first.post(f"/api/drafts/{draft['id']}/result", json=completion(draft, content))
    with TestClient(create_app(settings)) as second:
        assert second.get(f"/api/drafts/{draft['id']}").json()["status"] == "completed"


@pytest.mark.parametrize("field,value", [("input_hash", "0" * 64), ("draft_id", str(uuid4()))])
def test_cross_product_import_rejected(client, product, content, field, value):
    draft = create(client, product)
    payload = completion(draft, content)
    payload[field] = value
    assert client.post(f"/api/drafts/{draft['id']}/result", json=payload).status_code == 409
    assert client.get(f"/api/drafts/{draft['id']}").json()["status"] == "pending"


def test_completed_result_cannot_be_overwritten(client, product, content):
    draft = create(client, product)
    path = f"/api/drafts/{draft['id']}/result"
    assert client.post(path, json=completion(draft, content)).status_code == 200
    assert client.post(path, json=completion(draft, content)).status_code == 409


def test_bad_result_can_be_corrected(client, product, content):
    draft = create(client, product)
    bad = {**content, "seo_description": "Недостаточно длинное описание"}
    path = f"/api/drafts/{draft['id']}/result"
    assert client.post(path, json=completion(draft, bad)).status_code == 422
    assert client.post(path, json=completion(draft, content)).status_code == 200


def test_fabricated_value_rejected_at_import(client, product, content):
    draft = create(client, product)
    content["commercial_block"] = "Питание 999 В"
    assert (
        client.post(
            f"/api/drafts/{draft['id']}/result", json=completion(draft, content)
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "product",
    [
        {},
        {"name": " "},
        {"name": "Товар", "specs": []},
        {"name": "Товар", "specs": {"питание": 12}},
        {"name": "Товар", "unexpected": "поле"},
    ],
)
def test_bad_inputs(client, product):
    assert client.post("/api/drafts", json={"product": product}).status_code == 422


def test_malformed_json_and_empty_fields(client):
    response = client.post(
        "/api/drafts", content="{broken", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert "input" not in response.text
    draft = create(client, {"name": "Прибор", "manufacturer": "", "specs": {"точность": None}})
    assert draft["product"]["specs"]["точность"] is None


def test_missing_key_does_not_create_task(client, product):
    response = client.post("/api/drafts", json={"product": product, "provider": "openai"})
    assert response.status_code == 503
    assert client.get("/api/drafts").json() == []


def test_unknown_and_pending_resources(client, product):
    assert client.get(f"/api/drafts/{uuid4()}").status_code == 404
    assert client.get("/api/drafts/not-a-uuid").status_code == 422
    draft = create(client, product)
    assert client.get(f"/api/drafts/{draft['id']}/markdown").status_code == 409
    assert client.get("/api/drafts?limit=101").status_code == 422


def test_examples_use_same_pipeline(client):
    examples = client.get("/api/examples").json()
    assert len(examples) == 2
    for example in examples:
        draft = create(client, example["product"])
        response = client.post(
            f"/api/drafts/{draft['id']}/result", json=completion(draft, example["content"])
        )
        assert response.status_code == 200
        assert 800 <= len(response.json()["result"]["seo_description"]) <= 1200


def test_openai_success_uses_same_validation(tmp_path, monkeypatch, product, content):
    monkeypatch.setattr("app.main.generate_openai", lambda *_: GeneratedContent(**content))
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/openai.db", openai_api_key="test-key", _env_file=None
    )
    with TestClient(create_app(settings)) as client:
        result = client.post("/api/drafts", json={"product": product, "provider": "openai"})
        assert result.status_code == 201
        assert result.json()["status"] == "completed"
        assert result.json()["result"]["missing_fields"]


@pytest.mark.parametrize("status", [429, 502, 504])
def test_provider_error_persists_failed_state(tmp_path, monkeypatch, product, status):
    def fail(*args):
        raise ProviderError("Безопасное сообщение об ошибке", status)

    monkeypatch.setattr("app.main.generate_openai", fail)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/error.db", openai_api_key="test-key", _env_file=None
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/drafts", json={"product": product, "provider": "openai"})
        assert response.status_code == status
        draft_id = response.json()["detail"]["draft_id"]
        draft = client.get(f"/api/drafts/{draft_id}").json()
        assert draft["status"] == "failed"
        assert draft["result"] is None


def test_web_assets_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/health").json() == {"status": "ok"}
    assert "openai_api_key" not in client.get("/api/config").json()
