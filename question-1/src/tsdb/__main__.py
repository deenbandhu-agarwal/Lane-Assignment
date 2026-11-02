"""`python -m tsdb` -> run the HTTP server (uvicorn) on TSDB_HOST:TSDB_PORT (default 0.0.0.0:8080).
Engine settings come from TSDB_* variables (EngineConfig.from_env); TSDB_CRASH_AT turns on the
crash points (faults.EnvFaults, used by tests/crash)."""

from __future__ import annotations

import logging
import os

import uvicorn

from tsdb.api.app import create_app
from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig


def main() -> None:
    logging.basicConfig(level=os.environ.get("TSDB_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = build_database(EngineConfig.from_env())        # recovery runs here, before the port opens
    try:
        uvicorn.run(create_app(db), host=os.environ.get("TSDB_HOST", "0.0.0.0"),
                    port=int(os.environ.get("TSDB_PORT", "8080")), log_level="warning")
    finally:
        db.close()


if __name__ == "__main__":
    main()
