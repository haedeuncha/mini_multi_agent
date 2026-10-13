import json

from redis import Redis

from app.core.config import settings


def client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def save_snapshot(run_id: str, state: dict[str, object]) -> None:
    values = {name: json.dumps(value, ensure_ascii=False, default=str) for name, value in state.items()}
    with client() as redis:
        redis.hset(f"mini07:run:{run_id}", mapping=values)
        redis.expire(f"mini07:run:{run_id}", settings.run_ttl_seconds)


def load_snapshot(run_id: str) -> dict[str, object] | None:
    with client() as redis:
        values = redis.hgetall(f"mini07:run:{run_id}")
    return {name: json.loads(value) for name, value in values.items()} if values else None


def append_event(run_id: str, event: dict[str, object]) -> None:
    with client() as redis:
        redis.rpush(f"mini07:run:{run_id}:events", json.dumps(event, ensure_ascii=False, default=str))
        redis.expire(f"mini07:run:{run_id}:events", settings.run_ttl_seconds)


def load_events(run_id: str) -> list[dict[str, object]]:
    with client() as redis:
        values = redis.lrange(f"mini07:run:{run_id}:events", 0, -1)
    return [json.loads(value) for value in values]
