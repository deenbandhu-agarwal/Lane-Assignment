"""Tag filter language: parse to an AST, evaluate with set operations on a PostingSource (port).

Grammar (AND binds tighter than OR; keywords case-insensitive):
    expr     := and_expr ("OR" and_expr)*
    and_expr := factor ("AND" factor)*
    factor   := "(" expr ")" | KEY "=" VALUE | KEY "!=" VALUE
Values may be double-quoted.

Evaluation (no full scans):
    k=v   -> posting list
    k!=v  -> universe(metric) - posting(k=v)      (series without tag k match)
    AND   -> intersect, starting from the smallest list
    OR    -> union
"""

from __future__ import annotations

from dataclasses import dataclass

from tsdb.model import SeriesId
from tsdb.ports import PostingSource


@dataclass(frozen=True, slots=True)
class Eq:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class NotEq:
    key: str
    value: str


@dataclass(frozen=True, slots=True)
class And:
    children: tuple["FilterExpr", ...]


@dataclass(frozen=True, slots=True)
class Or:
    children: tuple["FilterExpr", ...]


FilterExpr = Eq | NotEq | And | Or


def parse(text: str) -> FilterExpr:
    """Raises FilterSyntaxError with the position of the problem."""
    raise NotImplementedError


def evaluate(expr: FilterExpr | None, postings: PostingSource, metric: str | None) -> list[SeriesId]:
    """Sorted ascending (the read path relies on it). None = every series of the metric."""
    raise NotImplementedError
