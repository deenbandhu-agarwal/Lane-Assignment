"""Tag filter language (seams 1-4). Filters F1-F8 are from docs/api-contract.md."""

import pytest

from tsdb.errors import FilterSyntaxError
from tsdb.query.filter import And, Eq, NotEq, Or, parse


def test_and_binds_tighter_than_or():
    assert parse("region=us-east OR region=us-west AND service=api") == Or((
        Eq("region", "us-east"),
        And((Eq("region", "us-west"), Eq("service", "api"))),
    ))


def test_brackets_override_precedence_f4_and_f5():
    assert parse("(region=us-east OR region=us-west) AND service=api") == And((
        Or((Eq("region", "us-east"), Eq("region", "us-west"))),
        Eq("service", "api"),
    ))
    assert parse("(a=1 OR a=2) AND b!=3") == And((Or((Eq("a", "1"), Eq("a", "2"))), NotEq("b", "3")))


def test_a_chain_of_the_same_operator_is_one_flat_node_and_keywords_ignore_case():
    assert parse("a=1 and b=2 AnD c=3") == And((Eq("a", "1"), Eq("b", "2"), Eq("c", "3")))
    assert parse("a=1 or a=2 OR a=3") == Or((Eq("a", "1"), Eq("a", "2"), Eq("a", "3")))


def test_single_matchers_and_the_allowed_bare_characters():
    assert parse("service=api") == Eq("service", "api")
    assert parse("host!=h1") == NotEq("host", "h1")
    assert parse("path=/v1/x.y:z_w-1") == Eq("path", "/v1/x.y:z_w-1")


def test_quoted_values_may_hold_spaces_operators_and_escaped_quotes():
    assert parse('env="prod east"') == Eq("env", "prod east")
    assert parse('q="a=b AND (c)"') == Eq("q", "a=b AND (c)")
    assert parse(r'q="say \"hi\" \\ bye"') == Eq("q", 'say "hi" \\ bye')
    assert parse("op=and") == Eq("op", "and")             # a keyword word is fine as a value


@pytest.mark.parametrize("text, position, words", [
    ("a=1 AND", 7, "expected a tag key"),          # nothing after AND
    ("(a=1", 4, "expected ')'"),
    ("a=1 b=2", 4, "expected AND, OR or end"),
    ("=1", 0, "expected a tag key"),
    ("a=", 2, "expected a value"),
    ("a 1", 2, "expected '=' or '!='"),
    ('a="open', 2, "unclosed quote"),
    ("a=1)", 3, "expected AND, OR or end"),
    ("a=1 & b=2", 4, "unexpected character"),
    ("", 0, "expected a tag key"),
    ('a="x" "y"', 6, "expected AND, OR or end"),   # error points at the START of "y"
])
def test_a_syntax_error_names_the_problem_and_its_position(text, position, words):
    with pytest.raises(FilterSyntaxError) as err:
        parse(text)

    assert err.value.position == position
    assert words in str(err.value)
