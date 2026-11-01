"""SeriesKey identity and canonical text (seams 1-2)."""

from tsdb.model import SeriesKey


def test_tag_order_does_not_change_the_series():
    a = SeriesKey.of("temperature", {"sensor": "roof", "city": "Delhi"})
    b = SeriesKey.of("temperature", {"city": "Delhi", "sensor": "roof"})

    assert a == b
    assert a.tags == (("city", "Delhi"), ("sensor", "roof"))
