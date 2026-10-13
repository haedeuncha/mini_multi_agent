from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import TypeVar

import httpx
from pydantic import BaseModel

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)
PROVIDERS = ("openai", "ollama", "gemma")


class ProviderExecutionError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool, retry_after_seconds: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def normalize_provider_error(provider: str, error: Exception) -> ProviderExecutionError:
    raw = str(error)
    status_code = getattr(error, "code", None) or getattr(error, "status_code", None)
    if "429" in raw or "RESOURCE_EXHAUSTED" in raw:
        match = re.search(r"retry\s*(?:delay|in|after)[^0-9]*(\d+)", raw, re.IGNORECASE)
        retry_after = int(match.group(1)) if match else None
        retry_message = f" 약 {retry_after}초 후 재시도할 수 있습니다." if retry_after else " 할당량 초기화 후 다시 시도하세요."
        return ProviderExecutionError(
            f"{provider} API 요청 한도를 초과했습니다." + retry_message + " 자동 Provider 대체는 수행하지 않았습니다.",
            code="quota_exhausted", retryable=retry_after is not None, retry_after_seconds=retry_after,
        )
    server_busy = status_code in {500, 502, 503, 504} or bool(re.search(r"\b(500|502|503|504)\b", raw))
    retryable = server_busy or isinstance(error, (TimeoutError, ConnectionError)) or "timeout" in type(error).__name__.lower() or "connect" in type(error).__name__.lower()
    return ProviderExecutionError(
        f"{provider} Provider 호출에 실패했습니다: {type(error).__name__}",
        code="provider_unavailable" if retryable else "provider_error", retryable=retryable,
    )

def model_for(provider: str) -> str:
    return {"openai": settings.openai_model, "ollama": settings.ollama_model, "gemma": settings.gemma_model}[provider]

async def status(provider: str) -> dict[str, object]:
    ready = bool(settings.openai_api_key) if provider == "openai" else True
    result: dict[str, object] = {"configured": ready, "model": model_for(provider)}
    if provider in {"ollama", "gemma"}:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{settings.ollama_base_url}/api/tags")
                response.raise_for_status()
            names = [item["name"] for item in response.json().get("models", [])]
            result.update({"reachable": True, "model_installed": any(name == model_for(provider) or name.startswith(model_for(provider) + ":") for name in names)})
        except Exception as error:
            result.update({"reachable": False, "model_installed": False, "error": str(error)})
    return result

def openai_agent(prompt: str, schema: type[T]) -> T:
    from openai import OpenAI
    # 요청마다 Client를 열고 닫아 이미 종료된 HTTP Client가 재사용되지 않게 합니다.
    with OpenAI(api_key=settings.openai_api_key) as client:
        response = client.responses.parse(model=settings.openai_model, input=prompt, text_format=schema)
    if response.output_parsed is None:
        raise RuntimeError("GPT 구조화 결과가 없습니다.")
    return response.output_parsed

async def generate(provider: str, prompt: str, schema: type[T]) -> tuple[T, dict[str, object]]:
    if provider not in PROVIDERS:
        raise ValueError(f"지원하지 않는 Provider입니다: {provider}")
    if provider == "openai" and not settings.openai_api_key:
        raise RuntimeError("openai API Key가 없습니다.")
    started = perf_counter()
    try:
        if provider == "openai":
            result = await asyncio.to_thread(openai_agent, prompt, schema)
        else:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{settings.ollama_base_url}/api/chat",
                    json={
                        "model": model_for(provider),
                        "messages": [{"role": "user", "content": prompt}],
                        "format": schema.model_json_schema(),
                        "stream": False,
                    },
                )
                response.raise_for_status()
                result = schema.model_validate_json(response.json()["message"]["content"])
    except ProviderExecutionError:
        raise
    except Exception as error:
        raise normalize_provider_error(provider, error) from None
    latency_ms = round((perf_counter() - started) * 1000, 2)
    return result, {"provider": provider, "model": model_for(provider), "latency_ms": latency_ms}
