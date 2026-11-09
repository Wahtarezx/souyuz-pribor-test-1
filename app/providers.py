from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.config import Settings
from app.prompts import build_messages
from app.schemas import GeneratedContent, Product


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def generate_openai(product: Product, settings: Settings) -> GeneratedContent:
    key = settings.openai_api_key.get_secret_value()
    if not key:
        raise ProviderError("Для режима OpenAI задайте OPENAI_API_KEY в .env", 503)
    try:
        with OpenAI(api_key=key, timeout=settings.openai_timeout_seconds, max_retries=1) as client:
            response = client.responses.parse(
                model=settings.openai_model,
                input=build_messages(product),
                text_format=GeneratedContent,
                max_output_tokens=3000,
                store=False,
            )
        if response.status != "completed" or response.output_parsed is None:
            raise ProviderError("Модель отказалась отвечать или вернула неполный результат")
        return response.output_parsed
    except APITimeoutError as exc:
        raise ProviderError("Истекло время ожидания OpenAI", 504) from exc
    except RateLimitError as exc:
        raise ProviderError("Лимит OpenAI исчерпан. Попробуйте позже", 429) from exc
    except APIConnectionError as exc:
        raise ProviderError("Не удалось соединиться с OpenAI", 502) from exc
    except APIStatusError as exc:
        raise ProviderError("OpenAI отклонил запрос. Проверьте ключ и доступ к модели") from exc
    except ValueError as exc:
        raise ProviderError("Ответ модели не соответствует схеме карточки") from exc
