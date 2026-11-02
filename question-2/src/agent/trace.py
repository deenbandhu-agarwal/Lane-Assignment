"""One JSONL trace file per run. Every line is one event; flushed as written so a crash keeps what happened."""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from pathlib import Path
from typing import Any


def _default(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    return repr(obj)


class Tracer:
    def __init__(self, path: Path, run_id: str) -> None:
        self.path = path
        self.run_id = run_id
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")

    @classmethod
    def new(cls, trace_dir: Path) -> Tracer:
        run_id = uuid.uuid4().hex[:12]
        stamp = time.strftime("%Y%m%dT%H%M%S")
        return cls(Path(trace_dir) / f"{stamp}-{run_id}.jsonl", run_id)

    def event(self, kind: str, **data: Any) -> None:
        line = {"ts": time.time(), "run_id": self.run_id, "event": kind, **data}
        self._f.write(json.dumps(line, default=_default, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self) -> None:
        self._f.close()


def read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
