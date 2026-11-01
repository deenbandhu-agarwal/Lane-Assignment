"""Bloom filter over series ids (seams 1-4).

Golden values come from the walkthrough example (q1-example/make_example.py, separate code):
step2 sst/1m/10.00/000001.sst Bloom block for series ids [1, 2, 3].
"""

from tsdb.sstable.bloom import BloomFilter, BloomFilterFactory


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


# Example Bloom block without its crc: m = 32 (u32) | k = 7 (u8) | 4 bytes of bits
EXAMPLE_BLOOM_1_2_3 = bytes.fromhex("20000000" "07" "72d5ccb7")


def test_ids_1_2_3_give_exactly_the_bits_in_the_example_file():
    bloom = BloomFilterFactory().new(expected_items=3, false_positive_rate=0.01)
    for i in (1, 2, 3):
        bloom.add(i)

    assert bloom.to_bytes() == EXAMPLE_BLOOM_1_2_3


def test_a_filter_loaded_from_bytes_answers_like_the_one_that_wrote_them():
    loaded = BloomFilterFactory().load(EXAMPLE_BLOOM_1_2_3)

    assert (loaded.m_bits, loaded.k) == (32, 7)
    assert all(loaded.may_contain(i) for i in (1, 2, 3))
    written = BloomFilterFactory().new(3, 0.01)
    for i in (1, 2, 3):
        written.add(i)
    assert [loaded.may_contain(i) for i in range(1, 200)] == [written.may_contain(i) for i in range(1, 200)]


def test_measured_false_positive_rate_is_close_to_the_1_percent_target():
    """Ids 1..10,000 added (sequential, as the catalog assigns them); 100,000 ids that are surely
    absent (20,001..120,000) checked. README reports the measured number."""
    bloom = BloomFilterFactory().new(10_000, 0.01)
    for i in range(1, 10_001):
        bloom.add(i)

    false_positives = sum(bloom.may_contain(i) for i in range(20_001, 120_001))

    assert 0.005 <= false_positives / 100_000 <= 0.015, false_positives
