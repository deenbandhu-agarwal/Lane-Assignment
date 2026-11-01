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

import re
from dataclasses import dataclass

from tsdb.errors import FilterSyntaxError
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
    return _Parser(text).parse()


_WORD = re.compile(r"[A-Za-z0-9_.\-:/]+")


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str          # "word" | "string" | "(" | ")" | "=" | "!=" | "end"
    text: str
    pos: int


def _tokens(text: str) -> list[_Token]:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()=":
            out.append(_Token(c, c, i))
            i += 1
        elif text.startswith("!=", i):
            out.append(_Token("!=", "!=", i))
            i += 2
        elif c == '"':
            value, i = _quoted(text, i)
            out.append(_Token("string", value, i))
        elif m := _WORD.match(text, i):
            out.append(_Token("word", m.group(), i))
            i = m.end()
        else:
            raise FilterSyntaxError(f"unexpected character {c!r}", i)
    out.append(_Token("end", "", len(text)))
    return out


def _quoted(text: str, start: int) -> tuple[str, int]:
    """Value of the quoted string at `start` (\\ and \" are escapes) and the index after it."""
    chars, i = [], start + 1
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text) and text[i + 1] in '"\\':
            chars.append(text[i + 1])
            i += 2
        elif c == '"':
            return "".join(chars), i + 1
        else:
            chars.append(c)
            i += 1
    raise FilterSyntaxError("unclosed quote", start)


class _Parser:
    def __init__(self, text: str) -> None:
        self._tokens = _tokens(text)
        self._i = 0

    def parse(self) -> FilterExpr:
        expr = self._expr()
        return expr

    def _expr(self) -> FilterExpr:
        return self._chain("OR", Or, self._and_expr)

    def _and_expr(self) -> FilterExpr:
        return self._chain("AND", And, self._factor)

    def _chain(self, keyword, node, child) -> FilterExpr:
        children = [child()]
        while self._peek().kind == "word" and self._peek().text.upper() == keyword:
            self._i += 1
            children.append(child())
        return children[0] if len(children) == 1 else node(tuple(children))

    def _factor(self) -> FilterExpr:
        tok = self._next()
        if tok.kind == "(":
            expr = self._expr()
            self._next()
            return expr
        key = tok.text
        op = self._next()
        value = self._next().text
        return Eq(key, value) if op.kind == "=" else NotEq(key, value)

    def _peek(self) -> _Token:
        return self._tokens[self._i]

    def _next(self) -> _Token:
        tok = self._tokens[self._i]
        self._i += 1
        return tok


def evaluate(expr: FilterExpr | None, postings: PostingSource, metric: str | None) -> list[SeriesId]:
    """Sorted ascending (the read path relies on it). None = every series of the metric."""
    raise NotImplementedError
