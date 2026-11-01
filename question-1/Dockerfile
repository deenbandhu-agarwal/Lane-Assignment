# Free-threaded CPython 3.14t, installed by uv (no official python:3.14t image).
FROM debian:bookworm-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=automatic \
    PYTHON_GIL=0 \
    TSDB_DATA_DIR=/data

WORKDIR /app

RUN uv python install 3.14t

# dependencies first (cached layer), then the project
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY tests ./tests
COPY bench ./bench
COPY README.md ./
RUN uv sync --frozen

EXPOSE 8080
CMD ["uv", "run", "--frozen", "--no-sync", "python", "-m", "tsdb"]
