"""OrderedStore contract (seams 1-3). Runs against EVERY entry in bootstrap.ORDERED_STORES, so a
new structure (e.g. a red-black tree) must pass the same tests. Expected order comes from
Python's sorted(), an independent oracle."""

import random
from pathlib import Path

import pytest

from tsdb.bootstrap import ORDERED_STORES
from tsdb.config import EngineConfig


@pytest.fixture(params=sorted(ORDERED_STORES))
def store(request):
    return ORDERED_STORES[request.param](random.Random(140), EngineConfig(data_dir=Path("unused")))


def test_random_inserts_come_back_in_sorted_key_order(store):
    rng = random.Random(7)
    keys = list({(rng.randrange(50), rng.randrange(1_000), -rng.randrange(100)) for _ in range(10_000)})
    rng.shuffle(keys)

    for k in keys:
        store.insert(k, float(k[1]))

    assert [k for k, _ in store] == sorted(keys)
    assert len(store) == len(keys)


def test_two_versions_of_one_point_are_both_kept_newest_first(store):
    store.insert((3, 1_730_368_800_000, -3), 32.5)    # seq 3
    store.insert((3, 1_730_368_800_000, -7), 33.0)    # seq 7, same series and time

    assert list(store) == [((3, 1_730_368_800_000, -7), 33.0),
                           ((3, 1_730_368_800_000, -3), 32.5)]
