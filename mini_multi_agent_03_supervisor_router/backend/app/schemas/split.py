"""[Workshop 4] Lab 10 · 공정 N빵 정산 입출력 계약.

workers.yaml의 output_contract 이름과 Class 이름이 같다.
금액 계산 결과는 LLM 계약이 아니라 split_calculator.py(Python)가 만든다.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.workflow import MessageRequest

SPLIT_WORKERS = ("receipt_agent", "situation_agent", "classifier_agent", "explainer_agent")


class SplitRequest(MessageRequest):
    """Lab 10 실행 요청. message 안에 GATHER-번호가 있어야 한다."""

    unit: Literal[1, 10, 100, 1000] = 100


class SplitSupervisorDecision(BaseModel):
    agent_id: Literal["split_supervisor_agent"]
    next_agent: Literal["receipt_agent", "situation_agent", "classifier_agent", "explainer_agent", "finish"]
    reason: str = Field(min_length=1)


class ReceiptItem(BaseModel):
    label: str = Field(min_length=1)
    amount: int


class ReceiptRound(BaseModel):
    round_id: str = Field(min_length=1)
    round_name: str = Field(min_length=1)
    payer: str = Field(min_length=1)
    items: list[ReceiptItem] = Field(min_length=1)


class SplitReceiptResult(BaseModel):
    agent_id: Literal["receipt_agent"]
    rounds: list[ReceiptRound] = Field(min_length=1)
    unreadable_lines: list[str] = Field(default_factory=list)


class PersonState(BaseModel):
    name: str = Field(min_length=1)
    rounds_attended: list[str] = Field(min_length=1)
    drinks: bool
    eat: Literal["적게", "보통", "많이"]


class SplitSituationResult(BaseModel):
    agent_id: Literal["situation_agent"]
    people: list[PersonState] = Field(min_length=1)
    missing_information: list[str] = Field(default_factory=list, max_length=5)


class ClassifiedItem(BaseModel):
    round_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["food", "alcohol", "equal", "personal"]
    owner: str | None = None

    @model_validator(mode="after")
    def owner_only_for_personal(self) -> "ClassifiedItem":
        if self.kind == "personal" and not self.owner:
            raise ValueError("personal 메뉴에는 owner가 필요합니다.")
        if self.kind != "personal":
            self.owner = None
        return self


class SplitClassificationResult(BaseModel):
    agent_id: Literal["classifier_agent"]
    items: list[ClassifiedItem] = Field(min_length=1)


class PersonExplanation(BaseModel):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)


class SplitExplanationResult(BaseModel):
    agent_id: Literal["explainer_agent"]
    lines: list[PersonExplanation] = Field(min_length=1)
