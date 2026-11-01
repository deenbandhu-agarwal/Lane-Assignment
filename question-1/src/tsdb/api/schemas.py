"""Request / response models (pydantic). Validation happens here, before the engine is called."""

from __future__ import annotations

from pydantic import BaseModel, Field


class WritePoint(BaseModel):
    metric: str = Field(min_length=1)
    tags: dict[str, str] = Field(default_factory=dict)
    timestamp: int = Field(ge=0)            # epoch ms
    value: float                            # NaN / +-Inf rejected by a validator


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


class SeriesListResponse(BaseModel):
    series: list[SeriesOut]


class DeleteResponse(BaseModel):
    deleted_series: int


class ErrorResponse(BaseModel):
    error: str
    detail: dict | None = None
