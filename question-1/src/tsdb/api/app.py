"""REST API. Thin: parse + validate, call the injected TimeSeriesStore, map errors to status codes.
It depends on the port, so API tests use a fake store and the engine can change freely.

    POST   /write    body: [WritePoint]                      -> 200 {"written": n}   (after fsync)
    GET    /query    metric, filter?, from, to, agg?, bucket? -> 200 QueryResponse
    GET    /series   metric?, filter?                        -> 200 SeriesListResponse
    DELETE /series   metric?, filter?, from, to              -> 200 {"deleted_series": n}
Errors: 400 ValidationError/FilterSyntaxError/QueryLimitError, 500 otherwise (JSON body always).
"""

from __future__ import annotations

from fastapi import FastAPI

from tsdb.ports import TimeSeriesStore


def create_app(store: TimeSeriesStore) -> FastAPI:
    """On startup, log whether the GIL is enabled (sys._is_gil_enabled())."""
    raise NotImplementedError
