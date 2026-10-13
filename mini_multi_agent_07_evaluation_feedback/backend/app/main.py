from fastapi import FastAPI

from app.routers.evaluation import router


app = FastAPI(title="Mini Multi-Agent 07 · Evaluation, Feedback, Retry and Tracing", version="1.0.0")
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "project": "mini_multi_agent_07_evaluation_feedback"}
