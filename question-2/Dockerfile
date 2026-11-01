FROM python:3.13-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# dependencies first (cached layer), then the project
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY tests ./tests
COPY corpus ./corpus
COPY README.md ./
RUN uv sync --frozen

CMD ["uv", "run", "--frozen", "--no-sync", "pytest", "-q"]
