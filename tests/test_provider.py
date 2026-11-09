import json

import httpx
import pytest
from openai import OpenAI

from app.config import Settings
from app.providers import ProviderError, generate_openai
from app.schemas import Product


def wire_transport(monkeypatch, handler):
    monkeypatch.setattr(
        "app.providers.OpenAI",
        lambda **kwargs: OpenAI(
            **{**kwargs, "max_retries": 0},
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )


def response_body(content):
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "test-model",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": json.dumps(content), "annotations": []}
                ],
            }
        ],
    }


def test_real_sdk_request_and_parsing(monkeypatch, product, content):
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert body["text"]["format"]["strict"] is True
        assert body["store"] is False
        assert json.loads(body["input"][1]["content"])["name"] == product["name"]
        return httpx.Response(200, json=response_body(content))

    wire_transport(monkeypatch, handler)
    result = generate_openai(
        Product(**product),
        Settings(database_url="sqlite://", openai_api_key="test", _env_file=None),
    )
    assert result.seo_description == content["seo_description"]


@pytest.mark.parametrize("code,expected", [(401, 502), (429, 429), (500, 502)])
def test_remote_errors_redacted(monkeypatch, product, code, expected):
    wire_transport(
        monkeypatch,
        lambda r: httpx.Response(
            code, json={"error": {"message": "secret-provider-detail", "type": "test_error"}}
        ),
    )
    with pytest.raises(ProviderError) as error:
        generate_openai(
            Product(**product),
            Settings(database_url="sqlite://", openai_api_key="test", _env_file=None),
        )
    assert error.value.status_code == expected
    assert "secret-provider-detail" not in str(error.value)


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
def test_network_errors(monkeypatch, product, exception, code):
    def handler(request):
        raise exception("transport failure", request=request)

    wire_transport(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        generate_openai(
            Product(**product),
            Settings(database_url="sqlite://", openai_api_key="test", _env_file=None),
        )
    assert error.value.status_code == code


@pytest.mark.parametrize("mode", ["refusal", "incomplete", "invalid"])
def test_unusable_model_response(monkeypatch, product, content, mode):
    body = response_body(content)
    if mode == "refusal":
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "No answer"}]
    elif mode == "incomplete":
        body["status"] = "incomplete"
        body["output"] = []
    else:
        body["output"][0]["content"][0]["text"] = '{"seo_title":"short"}'
    wire_transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ProviderError):
        generate_openai(
            Product(**product),
            Settings(database_url="sqlite://", openai_api_key="test", _env_file=None),
        )


def test_malformed_http_json(monkeypatch, product):
    wire_transport(
        monkeypatch,
        lambda r: httpx.Response(
            200, content=b"{broken", headers={"Content-Type": "application/json"}
        ),
    )
    with pytest.raises(ProviderError):
        generate_openai(
            Product(**product),
            Settings(database_url="sqlite://", openai_api_key="test", _env_file=None),
        )
