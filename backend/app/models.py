from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
Unit = Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]


class Candle(BaseModel):
    open_time: AwareDatetime
    close_time: AwareDatetime
    open: FiniteFloat
    high: FiniteFloat
    low: FiniteFloat
    close: FiniteFloat


class TimeframePack(BaseModel):
    timeframe: str
    candles: list[Candle]
    indicators: dict[str, list[FiniteFloat]]


class IngestRequest(BaseModel):
    instrument: str
    trigger_candle_time: AwareDatetime
    cbot_version: str
    sent_at: AwareDatetime
    context_version: str
    model: str
    timeframes: list[TimeframePack]


class PendingReview(BaseModel):
    signal_id: int
    action: Literal["KEEP", "INVALIDATE"]


class ModelOutput(BaseModel):
    setup_direction: Literal["BUY", "SELL", "NONE"]
    setup_zone_low: FiniteFloat | None = None
    setup_zone_high: FiniteFloat | None = None
    confirmation_entry_price: FiniteFloat | None = None
    pending_reviews: list[PendingReview] = []
    rationale: str = ""
    confidence: Unit | None = None

    @model_validator(mode="after")
    def _levels(self):
        if self.setup_direction == "NONE":
            self.setup_zone_low = self.setup_zone_high = self.confirmation_entry_price = None
            return self
        levels = (self.setup_zone_low, self.setup_zone_high, self.confirmation_entry_price)
        if any(level is None for level in levels):
            raise ValueError("BUY and SELL require setup_zone_low, setup_zone_high and confirmation_entry_price")
        if any(level <= 0 for level in levels):
            raise ValueError("price levels must be positive")
        if self.setup_zone_low > self.setup_zone_high:
            raise ValueError("setup_zone_low must not exceed setup_zone_high")
        return self


class ReflectionOutput(BaseModel):
    abstain: bool = False
    observed_fact: str = ""
    hypothesis: str = ""
    candidate_lesson: str = ""
    conditions: str = ""
    cited_signal_ids: list[int] = []
    model_confidence: Unit = 0.0
    uncertainty: str = ""

    @model_validator(mode="after")
    def _lesson_present(self):
        if not self.abstain and not self.candidate_lesson.strip():
            raise ValueError("candidate_lesson is required unless abstaining")
        return self


class EvidenceSelection(BaseModel):
    relevant_signal_ids: list[int] = []


class ValidationVerdict(BaseModel):
    verdict: Literal["PROMOTE", "KEEP_CANDIDATE", "REJECT", "RETIRE"]
    model_confidence: Unit
    reasoning: str = ""
