"""Settings from environment variables, with a minimal .env loader (no extra dependency).
Variables already set in the environment win over .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # question-2/


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Settings:
    model_provider: str
    model_name: str
    gemini_api_key: str
    github_token: str
    github_repo: str
    write_allowlist: frozenset[str]
    max_cost_usd: float
    max_steps: int
    step_timeout_s: float
    retrieval_mode: str
    embed_model: str
    seed: int
    model_rpm: float
    corpus_dir: Path
    cache_dir: Path
    trace_dir: Path

    @classmethod
    def from_env(cls, dotenv: Path | None = ROOT / ".env") -> Settings:
        if dotenv is not None:
            load_dotenv(dotenv)
        e = os.environ.get
        repo = e("GITHUB_REPO", "")
        return cls(
            model_provider=e("MODEL_PROVIDER", "gemini"),
            model_name=e("MODEL_NAME", "gemini-3.5-flash"),
            gemini_api_key=e("GEMINI_API_KEY", ""),
            github_token=e("GITHUB_TOKEN", ""),
            github_repo=repo,
            write_allowlist=frozenset(r.strip() for r in e("WRITE_REPO_ALLOWLIST", repo).split(",") if r.strip()),
            max_cost_usd=float(e("MAX_COST_USD", "5")),
            max_steps=int(e("MAX_STEPS", "10")),
            step_timeout_s=float(e("STEP_TIMEOUT_S", "90")),
            retrieval_mode=e("RETRIEVAL_MODE", "hybrid"),
            embed_model=e("EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
            seed=int(e("SEED", "42")),
            model_rpm=float(e("MODEL_RPM", "0")),
            corpus_dir=Path(e("CORPUS_DIR", str(ROOT / "corpus"))),
            cache_dir=Path(e("CACHE_DIR", str(ROOT / ".cache"))),
            trace_dir=Path(e("TRACE_DIR", str(ROOT / "traces"))),
        )
