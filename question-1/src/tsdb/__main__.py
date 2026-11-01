"""`python -m tsdb` -> run the HTTP server (uvicorn) on TSDB_HOST:TSDB_PORT (default 0.0.0.0:8080).
main(): config = EngineConfig.from_env(); db = bootstrap.build_database(config);
uvicorn.run(api.app.create_app(db))."""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
