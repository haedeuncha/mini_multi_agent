from app.schemas.contracts import TraceEvent
from app.storage.redis_store import append_event, save_snapshot


class EvaluationTracker:
    def __init__(self, run_id: str, state: dict[str, object]):
        self.run_id = run_id
        self.state = state
        self.sequence = 0
        save_snapshot(run_id, state)

    def record(
        self,
        stage: str,
        actor: str,
        status: str,
        message: str,
        *,
        progress: int,
        round_number: int | None = None,
        attempt: int = 1,
        details: dict[str, object] | None = None,
    ) -> None:
        self.sequence += 1
        event = TraceEvent(
            sequence=self.sequence,
            stage=stage,
            actor=actor,
            status=status,
            round_number=round_number,
            attempt=attempt,
            message=message,
            details=details or {},
        ).model_dump()
        append_event(self.run_id, event)
        self.state.update(
            {
                "current_stage": stage,
                "current_actor": actor,
                "current_status": status,
                "message": message,
                "progress": min(progress, 95),
                "current_round": round_number,
            }
        )
        save_snapshot(self.run_id, self.state)

    def finish(self, status: str, result: dict[str, object] | None) -> None:
        self.state.update(
            {
                "status": status,
                "current_status": status,
                "progress": 100,
                "result": result,
            }
        )
        save_snapshot(self.run_id, self.state)
