"""SwapLock (seam E2, design-qa #45 D2). Threads are ordered with events, not sleeps, except for
short 'must NOT happen yet' waits."""

import threading

from tsdb.engine.swap_lock import SwapLock

NOT_YET = 0.05      # seconds to wait for something that must not happen


def hold_shared(lock, entered, release):
    with lock.shared():
        entered.set()
        release.wait()


def start(target, *args):
    t = threading.Thread(target=target, args=args)
    t.start()
    return t


def test_many_writers_hold_it_shared_at_the_same_time():
    lock = SwapLock()
    in_a, in_b, release = threading.Event(), threading.Event(), threading.Event()
    a, b = start(hold_shared, lock, in_a, release), start(hold_shared, lock, in_b, release)

    assert in_a.wait(1) and in_b.wait(1)
    release.set()
    a.join(), b.join()


def test_the_swap_waits_until_every_writer_in_flight_has_finished():
    lock = SwapLock()
    in_a, release = threading.Event(), threading.Event()
    a = start(hold_shared, lock, in_a, release)
    in_a.wait(1)
    swapped = threading.Event()

    def swap():
        with lock.exclusive():
            swapped.set()

    s = start(swap)
    assert not swapped.wait(NOT_YET)        # a group is still between "take seq" and "applied"
    release.set()
    assert swapped.wait(1)
    a.join(), s.join()


def test_a_waiting_swap_stops_new_writers_from_starting_so_it_cannot_starve():
    lock = SwapLock()
    in_a, release_a = threading.Event(), threading.Event()
    a = start(hold_shared, lock, in_a, release_a)
    in_a.wait(1)
    swapped, swap_release = threading.Event(), threading.Event()

    def swap():
        with lock.exclusive():
            swapped.set()
            swap_release.wait()

    s = start(swap)
    assert not swapped.wait(NOT_YET)        # swap is now waiting for writer A
    in_c, release_c = threading.Event(), threading.Event()
    c = start(hold_shared, lock, in_c, release_c)

    assert not in_c.wait(NOT_YET)           # new writer C waits behind the swap
    release_a.set()
    assert swapped.wait(1)
    assert not in_c.is_set()                # still blocked while the swap runs
    swap_release.set()
    assert in_c.wait(1)                     # after the swap, writers go on
    release_c.set()
    a.join(), s.join(), c.join()
