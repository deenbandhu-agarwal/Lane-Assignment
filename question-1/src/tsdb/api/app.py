"""REST API. Thin: parse + validate, call the injected TimeSeriesStore, map errors to status codes.
It depends on the port, so the engine can change freely. Contract: docs/api-contract.md.

    POST   /write    body: [WritePoint]                      -> 200 {"written": n}   (after fsync)
    GET    /query    metric, filter?, from, to, agg?, bucket? -> 200 QueryResponse
    GET    /series   metric?, filter?                        -> 200 SeriesListResponse
    DELETE /series   metric?, filter?, from, to              -> 200 {"deleted_series": n}
Errors: always JSON {"error": text, "detail": {...}?}
    400  bad body / parameter, filter syntax (detail.position), bad point (detail.index), query limit
    500  anything else (e.g. a failed fsync: the store refuses every later write)
Handlers are plain `def`: FastAPI runs them on its thread pool, and with the GIL off they really
run in parallel. The WAL group commit is where concurrent writes meet.
"""

from __future__ import annotations

import json
import logging
import sys

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from starlette.concurrency import run_in_threadpool   # blocking engine call (waits for fsync)

from tsdb.api.schemas import (MAX_BATCH, DeleteResponse, QueryResponse, SeriesListResponse, SeriesOut,
                              SeriesPoints, WritePoint, WriteResponse)
from tsdb.errors import FilterSyntaxError, ValidationError
from tsdb.model import Aggregation, SeriesKey
from tsdb.ports import TimeSeriesStore
from tsdb.query.aggregate import parse_bucket

log = logging.getLogger("tsdb.api")


def create_app(store: TimeSeriesStore) -> FastAPI:
    app = FastAPI(title="tsdb")
    gil = sys._is_gil_enabled() if hasattr(sys, "_is_gil_enabled") else True
    log.info("GIL enabled: %s", gil)

    @app.exception_handler(ValidationError)
    def bad_input(_: Request, e: ValidationError) -> JSONResponse:
        detail = ({"position": e.position} if isinstance(e, FilterSyntaxError)
                  else {"index": e.index} if isinstance(e, _PointError) else None)
        return _error(400, str(e), detail)

    @app.exception_handler(RequestValidationError)
    def bad_parameter(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0]
        return _error(400, f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}")

    @app.exception_handler(Exception)
    def failure(_: Request, e: Exception) -> JSONResponse:
        log.exception("request failed")
        return _error(500, f"{type(e).__name__}: {e}")

    @app.post("/write", response_model=WriteResponse)
    async def write(request: Request) -> WriteResponse:
        try:
            body = json.loads(await request.body())
        except ValueError as e:
            raise ValidationError(f"body is not JSON: {e}") from None
        points = _validate_batch(body)
        written = await run_in_threadpool(store.write, [(SeriesKey.of(p.metric, p.tags), p.timestamp, p.value)
                                                 for p in points])
        return WriteResponse(written=written)

    @app.get("/query", response_model=QueryResponse, response_model_exclude_none=True)
    def query(metric: str, from_: int = Query(alias="from"), to: int = Query(),
              filter: str | None = None, agg: str | None = None, bucket: str | None = None) -> QueryResponse:
        _check_range(from_, to)
        aggregation = _aggregation(agg)
        if bucket is not None and aggregation is None:
            raise ValidationError("bucket needs agg (avg|sum|min|max|count)")
        bucket_ms = parse_bucket(bucket) if bucket is not None else None
        result = store.query(metric, filter, from_, to, aggregation, bucket_ms)
        series = []
        for s in result.series:
            out = SeriesPoints(metric=s.key.metric, tags=dict(s.key.tags))
            if aggregation is None:
                out.points = s.points
            else:
                out.agg, out.bucket_ms, out.buckets = aggregation.value, bucket_ms, s.points
            series.append(out)
        return QueryResponse(series=series, stats=result.stats)

    @app.get("/series", response_model=SeriesListResponse)
    def list_series(metric: str | None = None, filter: str | None = None) -> SeriesListResponse:
        result = store.list_series(metric, filter)
        return SeriesListResponse(series=[SeriesOut(metric=k.metric, tags=dict(k.tags)) for k in result.series])

    @app.delete("/series", response_model=DeleteResponse)
    def delete(from_: int = Query(alias="from"), to: int = Query(), metric: str | None = None,
               filter: str | None = None) -> DeleteResponse:
        if not metric and not (filter and filter.strip()):
            raise ValidationError("give a metric or a filter (no delete-everything by accident)")
        _check_range(from_, to)
        return DeleteResponse(deleted_series=store.delete(metric, filter, from_, to))

    return app


def _validate_batch(body: object) -> list[WritePoint]:
    """Whole batch or nothing: the first bad point rejects the batch and is named by its index."""
    if not isinstance(body, list) or not body:
        raise ValidationError("body must be a non-empty JSON array of points")
    if len(body) > MAX_BATCH:
        raise ValidationError(f"at most {MAX_BATCH} points per request, got {len(body)}")
    points = []
    for i, raw in enumerate(body):
        try:
            points.append(WritePoint.model_validate(raw))
        except PydanticValidationError as e:
            first = e.errors()[0]
            raise _PointError(i, f"point {i}: {'.'.join(str(p) for p in first['loc']) or 'point'}: "
                                 f"{first['msg']}") from None
    return points


class _PointError(ValidationError):
    def __init__(self, index: int, message: str) -> None:
        super().__init__(message)
        self.index = index


def _check_range(from_ts: int, to_ts: int) -> None:
    if from_ts > to_ts:
        raise ValidationError(f"from ({from_ts}) is after to ({to_ts})")


def _aggregation(text: str | None) -> Aggregation | None:
    if text is None:
        return None
    try:
        return Aggregation(text)
    except ValueError:
        raise ValidationError(f"unknown agg {text!r}: use avg|sum|min|max|count") from None


def _error(status: int, message: str, detail: dict | None = None) -> JSONResponse:
    body: dict = {"error": message}
    if detail:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)
