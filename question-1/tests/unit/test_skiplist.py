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


T0 = 1_730_368_800_000          # 10:00
T1 = 1_730_368_860_000          # 10:01
T2 = 1_730_368_920_000          # 10:02
FIVE = [(1, T0, -1), (1, T1, -4), (2, T0, -2), (3, T0, -10), (3, T0, -3)]


@pytest.fixture
def five(store):
    for k in reversed(FIVE):
        store.insert(k, 0.0)
    return store


def test_iter_from_an_existing_key_starts_at_that_key(five):
    assert [k for k, _ in five.iter_from((2, T0, -2))] == FIVE[2:]


def test_iter_from_a_key_between_entries_starts_at_the_next_bigger_key(five):
    assert [k for k, _ in five.iter_from((1, T2, -999))] == FIVE[2:]   # past series 1, before series 2
    assert [k for k, _ in five.iter_from((3, T0, -5))] == FIVE[4:]     # between seq 10 and seq 3


def test_iter_from_before_everything_gives_all_and_after_everything_gives_nothing(five):
    assert [k for k, _ in five.iter_from((0, 0, 0))] == FIVE
    assert list(five.iter_from((4, 0, 0))) == []


def test_a_reader_walking_during_inserts_never_sees_a_broken_list(store):
    """Free-threaded (3.14t): one writer, one reader at the same time, no lock on the read side.
    Every walk must be sorted and must hold every key inserted before that walk started.

    SMOKE TEST ONLY. Checked by mutation: publishing a node before setting its `next` pointers
    (the real bug this guards) was NOT caught in 3/3 runs, even with 4 readers doing ~150K short
    walks; the unsafe gap is two statements wide. Safety of the publish order rests on the
    argument in skiplist.py (node fully built, then one reference store per level), not on
    this test. It does catch crashes and lost keys under real parallel (GIL off) access."""
    import threading

    rng = random.Random(11)
    keys = list({(rng.randrange(1_000), rng.randrange(10_000), -1) for _ in range(100_000)})
    rng.shuffle(keys)
    done_count = 0                       # keys[:done_count] are fully inserted (only writer moves it)
    finished = threading.Event()
    problems: list[str] = []
    walks = 0

    def writer():
        nonlocal done_count
        for k in keys:
            store.insert(k, 0.0)
            done_count += 1
        finished.set()

    def reader():
        nonlocal walks
        while not finished.is_set():
            before = set(keys[:done_count])
            seen = [k for k, _ in store]
            walks += 1
            if seen != sorted(seen):
                problems.append(f"walk {walks}: not sorted")
            missing = before - set(seen)
            if missing:
                problems.append(f"walk {walks}: {len(missing)} keys missing")

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert problems == []
    assert walks > 1                     # the reader really overlapped the writer
    assert [k for k, _ in store] == sorted(keys)
