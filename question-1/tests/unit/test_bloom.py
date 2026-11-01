"""Bloom filter over series ids (seams 1-4).

Golden values come from the walkthrough example (q1-example/make_example.py, separate code):
step2 sst/1m/10.00/000001.sst Bloom block for series ids [1, 2, 3].
"""

from tsdb.sstable.bloom import BloomFilter


def test_sizing_for_10k_ids_at_1_percent():
    # m = ceil(-10000 * ln(0.01) / ln(2)^2) = ceil(95850.58) = 95851 -> whole bytes -> 95856
    # k = round(95856 / 10000 * ln 2) = round(6.644) = 7
    assert BloomFilter.optimal_params(10_000, 0.01) == (95_856, 7)


def test_sizing_for_the_three_ids_in_the_example_file():
    # m = ceil(28.76) = 29 -> 32 ; k = round(32 / 3 * ln 2) = round(7.39) = 7
    assert BloomFilter.optimal_params(3, 0.01) == (32, 7)


def test_every_added_id_is_reported_as_maybe_present():
    bloom = BloomFilter(*BloomFilter.optimal_params(10_000, 0.01))
    ids = range(1, 10_001)

    for i in ids:
        bloom.add(i)

    assert all(bloom.may_contain(i) for i in ids)
