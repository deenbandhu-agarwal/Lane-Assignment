"""WAL routing (seam 7). Expected indexes are fixed literals: standard CRC-32 of the canonical
text mod N. Python's hash() would give a different answer on every process start."""

from tsdb.model import SeriesKey
from tsdb.wal.routing import HashWalRouter

DELHI_ROOF = SeriesKey.of("temperature", {"city": "Delhi", "sensor": "roof"})
MUMBAI_ROOF = SeriesKey.of("temperature", {"city": "Mumbai", "sensor": "roof"})


def test_a_series_always_goes_to_the_same_wal_fixed_by_crc32_of_its_canonical_text():
    router = HashWalRouter(wal_count=4)

    assert router.route(DELHI_ROOF) == 3
    assert router.route(MUMBAI_ROOF) == 1


def test_route_is_always_a_valid_wal_index():
    router = HashWalRouter(wal_count=3)
    keys = [SeriesKey.of("cpu", {"host": f"h{i}"}) for i in range(200)]

    assert {router.route(k) for k in keys} == {0, 1, 2}
