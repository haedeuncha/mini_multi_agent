from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class EvaluationRunRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=50)
    request: str = Field(min_length=10, max_length=1000)
    demonstrate_revision: bool = True

    @field_validator("user_id", "request")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


class WritingResult(BaseModel):
    title: str
    content: str
    included_requirements: list[str] = Field(default_factory=list, max_length=10)


class EvaluationResult(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    feedback: str
    passed_criteria: list[str] = Field(default_factory=list, max_length=20)
    failed_criteria: list[str] = Field(default_factory=list, max_length=20)


class TravelGuideDay(BaseModel):
    day: int = Field(ge=1, le=30)
    guide: str = Field(min_length=1, max_length=500)


class TravelGuideResult(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    weather_tip: str = Field(min_length=1, max_length=500)
    schedule: list[TravelGuideDay] = Field(min_length=1, max_length=30)
    notice: str = Field(min_length=1, max_length=500)


class TraceEvent(BaseModel):
    sequence: int
    stage: str
    actor: str
    status: str
    round_number: int | None = None
    attempt: int = 1
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class SupportEvaluationRequest(BaseModel):
    request: str = Field(default="로그인 오류 고객에게 확인 절차를 안내해 주세요.", min_length=10, max_length=500)
    demonstrate_revision: bool = True

    @field_validator("request")
    @classmethod
    def support_request_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


class TravelBookingStartRequest(BaseModel):
    """통합 여행 예약 예제의 1단계 요청입니다.

    사용자는 목적지, 날씨, 취향을 입력합니다. Backend는 이 정보를 보고 장소 후보와
    숙소 후보를 만들고, 추천 품질을 간단한 Python 기준으로 평가합니다.
    """

    user_id: str = Field(default="user-101", min_length=1, max_length=50)
    destination: str = Field(default="부산", pattern="^부산$")
    weather: str = Field(default="비", min_length=1, max_length=30)
    actual_weather: dict[str, object] = Field(default_factory=dict)
    preferences: list[str] = Field(default_factory=lambda: ["실내", "맛집"], max_length=5)

    @field_validator("user_id", "destination", "weather")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


class TravelPlaceSelectRequest(BaseModel):
    """09 통합 예제에서 장소를 선택한 뒤 숙소를 검색하는 요청입니다."""

    run_id: str = Field(min_length=1, max_length=80)
    user_id: str = Field(default="user-101", min_length=1, max_length=50)
    place_id: str = Field(min_length=1, max_length=50)

    @field_validator("run_id", "user_id", "place_id")
    @classmethod
    def selection_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


class TravelPlanApprovalRequest(BaseModel):
    """선택한 숙소·일정·인원으로 예산과 가이드를 만드는 1차 승인입니다."""

    run_id: str = Field(min_length=1, max_length=80)
    user_id: str = Field(default="user-101", min_length=1, max_length=50)
    hotel_id: str = Field(min_length=1, max_length=50)
    check_in: date = Field(default_factory=lambda: date.today() + timedelta(days=1))
    check_out: date = Field(default_factory=lambda: date.today() + timedelta(days=2))
    guest_count: int = Field(default=2, ge=1, le=10)
    approved: bool = False

    @field_validator("run_id", "user_id", "hotel_id")
    @classmethod
    def plan_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()

    @model_validator(mode="after")
    def check_plan_approval(self):
        if self.check_out <= self.check_in:
            raise ValueError("체크아웃 날짜는 체크인 날짜보다 늦어야 합니다.")
        if not self.approved:
            raise ValueError("여행 계획과 예산 생성을 먼저 승인해야 합니다.")
        return self


class TravelBookingConfirmRequest(BaseModel):
    """생성된 예산과 가이드를 확인한 뒤 실제 예약을 실행하는 2차 승인입니다.

    호텔·날짜·인원은 1차 승인 때 Redis Snapshot에 고정합니다. 2차 승인 요청은 이를
    다시 보내지 않으므로 승인 뒤 실행 인자가 바뀌지 않습니다.
    """

    run_id: str = Field(min_length=1, max_length=80)
    user_id: str = Field(default="user-101", min_length=1, max_length=50)
    approved: bool = False
    failure_scenario: Literal["normal", "fail_once", "fail_twice"] = "normal"

    @field_validator("run_id", "user_id")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()

    @model_validator(mode="after")
    def check_booking_approval(self):
        if not self.approved:
            raise ValueError("전체 예산과 여행 가이드를 확인하고 실제 예약을 승인해야 합니다.")
        return self


class BookingRecoveryDemoRequest(BaseModel):
    """11 원클릭 복구 실습의 시작 요청입니다."""

    user_id: str = Field(default="user-110", min_length=1, max_length=50)
    destination: str = Field(default="부산", pattern="^부산$")
    failure_scenario: Literal["normal", "fail_once", "fail_twice"] = "fail_once"
    auto_approve: bool = False

    @field_validator("user_id", "destination")
    @classmethod
    def recovery_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()

    @model_validator(mode="after")
    def check_demo_approval(self):
        if not self.auto_approve:
            raise ValueError("수업용 1차·2차 자동 승인에 동의해야 합니다.")
        return self
