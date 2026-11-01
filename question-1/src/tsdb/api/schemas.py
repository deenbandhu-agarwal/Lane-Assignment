"""Request / response models (pydantic). Validation happens here, before the engine is called."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_BATCH = 10_000


class WritePoint(BaseModel):
    model_config = ConfigDict(strict=True)   # "5" is not a number, 5 is not a tag value

    metric: str = Field(min_length=1)
    tags: dict[str, str] = Field(default_factory=dict)
    timestamp: int = Field(ge=0)            # epoch ms
    value: float

    @field_validator("value", mode="before")
    @classmethod
    def finite(cls, v):
        if isinstance(v, bool):
            raise ValueError("value must be a number")
        if isinstance(v, int):
            v = float(v)                    # 30 is a fine value; strict mode would refuse it
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("value must be finite (NaN and Infinity are not stored)")
        return v


class WriteResponse(BaseModel):
    written: int


class SeriesOut(BaseModel):
    metric: str
    tags: dict[str, str]


class SeriesPoints(SeriesOut):
    points: list[tuple[int, float]] | None = None
    agg: str | None = None
    bucket_ms: int | None = None
    buckets: list[tuple[int, float]] | None = None


class QueryResponse(BaseModel):
    series: list[SeriesPoints]
    stats: dict[str, int] = Field(default_factory=dict)   # tables / blocks touched (README read path)


class SeriesListResponse(BaseModel):
    series: list[SeriesOut]


class DeleteResponse(BaseModel):
    deleted_series: int


class ErrorResponse(BaseModel):
    error: str
    detail: dict | None = None
