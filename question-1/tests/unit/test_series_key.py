"""SeriesKey identity and canonical text (seams 1-2)."""

from tsdb.model import SeriesKey


def test_tag_order_does_not_change_the_series():
    a = SeriesKey.of("temperature", {"sensor": "roof", "city": "Delhi"})
    b = SeriesKey.of("temperature", {"city": "Delhi", "sensor": "roof"})

    assert a == b
    assert a.tags == (("city", "Delhi"), ("sensor", "roof"))


def test_canonical_text_is_metric_then_sorted_tags_in_braces():
    assert SeriesKey.of("temperature", {"sensor": "roof", "city": "Delhi"}).canonical() \
        == "temperature{city=Delhi,sensor=roof}"
    assert SeriesKey.of("uptime", {}).canonical() == "uptime{}"


def test_special_characters_are_escaped_so_two_series_never_share_a_text():
    one_tag = SeriesKey.of("m", {"a": "1,b=2"})
    two_tags = SeriesKey.of("m", {"a": "1", "b": "2"})

    assert one_tag.canonical() == r"m{a=1\,b\=2}"
    assert two_tags.canonical() == "m{a=1,b=2}"
    assert SeriesKey.of("x{y}", {"k\\": "v"}).canonical() == r"x\{y\}{k\\=v}"
