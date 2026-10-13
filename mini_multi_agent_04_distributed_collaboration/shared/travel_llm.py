from __future__ import annotations

import os
from time import perf_counter
from typing import TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

from shared.travel_contracts import LearningAgentResult


load_dotenv()
T = TypeVar("T", bound=BaseModel)
SUPPORTED_PROVIDERS = ("openai", "gemini", "ollama", "gemma")
DEFAULT_AGENT_PROVIDERS = {
    "weather_agent": "openai", 
    "place_agent": "ollama",
    "budget_agent": "openai",
    "safety_agent": "gemma",
    "research_agent": "openai",
    "writer_agent": "openai",
    "reviewer_agent": "gemma",
    "router_agent": "openai",
    "supervisor_agent": "openai",
    "analyst_agent": "openai",
    "developer_agent": "ollama",
    "support_agent": "openai",
    "delivery_agent": "openai",
    "technical_support_agent": "ollama",
    "refund_agent": "gemma",
    "evaluator_agent": "openai",
    "reviser_agent": "openai",
    "itinerary_agent": "gemma",
}


def provider_model(provider: str) -> str:
    models = {
        "openai": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "gemini": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "ollama": os.getenv("OLLAMA_MODEL", "llama3.2"),
        "gemma": os.getenv("GEMMA_MODEL", "gemma3:4b"),
    }
    if provider not in models:
        raise ValueError(f"지원하지 않는 Provider입니다: {provider}")
    return models[provider]


def run_structured(provider: str, prompt: str, schema: type[T]) -> T:
    """같은 Pydantic 계약을 실제 OpenAI·Gemini·Ollama 요청으로 변환합니다."""
    model = provider_model(provider)
    if provider == "openai":
        from openai import OpenAI

        # Keep the client alive for the entire request. Creating it as a
        # temporary expression can let its underlying HTTP client be closed
        # before the SDK has finished consuming the response.
        with OpenAI() as client:
            response = client.responses.parse(model=model, input=prompt, text_format=schema)
        if response.output_parsed is None:
            raise RuntimeError("OpenAI가 구조화된 결과를 반환하지 않았습니다.")
        return response.output_parsed
    if provider == "gemini":
        from google import genai

        # Do not create Client inline. google-genai may garbage-collect that
        # temporary object and close httpx while generate_content is running.
        with genai.Client(api_key=os.environ["GEMINI_API_KEY"]) as client:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_json_schema": schema.model_json_schema(),
                },
            )
        if not response.text:
            raise RuntimeError("Gemini가 구조화된 결과를 반환하지 않았습니다.")
        return schema.model_validate_json(response.text)
    if provider in {"ollama", "gemma"}:
        base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "format": schema.model_json_schema(),
                "stream": False,
            },
            timeout=90,
        )
        response.raise_for_status()
        return schema.model_validate_json(response.json()["message"]["content"])
    raise ValueError(f"지원하지 않는 Provider입니다: {provider}")


def run_with_metadata(provider: str, prompt: str, schema: type[T]) -> dict:
    started = perf_counter()
    try:
        result = run_structured(provider, prompt, schema)
        return {
            "provider_requested": provider,
            "provider_used": provider,
            "model": provider_model(provider),
            "fallback_used": False,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "result": result.model_dump(),
            "error": None,
        }
    except Exception as error:
        return {
            "provider_requested": provider,
            "provider_used": None,
            "model": provider_model(provider),
            "fallback_used": False,
            "latency_ms": round((perf_counter() - started) * 1000, 2),
            "result": None,
            "error": f"{type(error).__name__}: {error}",
        }


def provider_for_agent(agent_id: str) -> str:
    """Agent별 Provider를 환경 변수로 바꿀 수 있게 합니다."""
    default_provider = DEFAULT_AGENT_PROVIDERS.get(agent_id, "openai")
    env_name = f"{agent_id.upper()}_PROVIDER"
    return os.getenv(env_name, default_provider)


def run_learning_agent(agent_id: str, goal: str, request: str, context: object | None = None) -> dict:
    """초보자 예제용 공통 AI Agent 실행 함수입니다."""
    provider = provider_for_agent(agent_id)
    prompt = f"""
당신은 {agent_id}입니다.
Goal: {goal}
다른 Agent의 역할을 대신하지 마세요.
요청: {request}
이전 Agent가 전달한 Context: {context}
LearningAgentResult 형식으로 반환하고 agent_id는 반드시 {agent_id}로 작성하세요.
""".strip()
    response = run_with_metadata(provider, prompt, LearningAgentResult)
    if response["result"] is not None:
        # Agent identity belongs to the orchestrator, not to model-generated
        # content. Some local models confuse it with a domain identifier such
        # as a place ID (for example P001), so stamp the trusted caller value.
        response["result"]["agent_id"] = agent_id
    return response


def run_learning_agent_with_failover(
    agent_id: str,
    goal: str,
    request: str,
    providers: tuple[str, ...],
) -> dict:
    """실제 Provider를 순서대로 시도하고 모든 실패 기록을 보존합니다."""
    attempts = []
    for provider in providers:
        prompt = f"당신은 {agent_id}입니다. Goal: {goal}\n요청: {request}\nagent_id는 반드시 {agent_id}입니다."
        response = run_with_metadata(provider, prompt, LearningAgentResult)
        if response["result"] is not None:
            response["result"]["agent_id"] = agent_id
        attempts.append({
            "provider": provider,
            "model": response["model"],
            "error": response["error"],
        })
        if response["result"] is not None:
            return {**response, "attempts": attempts, "failover_used": len(attempts) > 1}
    return {
        "provider_requested": providers[0],
        "provider_used": None,
        "model": None,
        "fallback_used": False,
        "failover_used": len(attempts) > 1,
        "result": None,
        "error": "모든 실제 LLM Provider가 실패했습니다.",
        "attempts": attempts,
    }
