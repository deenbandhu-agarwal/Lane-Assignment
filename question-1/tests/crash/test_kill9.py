"""kill -9 from outside at a random moment, while 4 client threads write and delete; 20 rounds on
the SAME data folder (recovery after recovery). Seeded: a failure replays with the same timings."""

import random
import threading
import time

import pytest

from tests.crash.harness import Client, Model, Server, check, check_files, read_all, workload

pytestmark = pytest.mark.crash

THREADS = 4
ROUNDS = 20


@pytest.mark.parametrize("wal_count", [1, 2])
def test_kill9_during_writes_loses_no_acked_write(tmp_path, wal_count):
    data = tmp_path / "data"
    rng = random.Random(9)
    models = [Model() for _ in range(THREADS)]        # each thread owns its cities
    confirmed_total = 0
    for round_no in range(ROUNDS):
        server = Server(data, wal_count)
        if round_no:                                   # what the last crash left must match
            actual = read_all(server.url)
            for t, model in enumerate(models):
                mine = {k: v for k, v in actual.items() if k[0].startswith(f"t{t}-")}
                check(mine, model)
                model.in_flight, model.confirmed = [], mine
        stop = threading.Event()

        def writer(t, model):
            client = Client(server.url, model)
            cities = [f"t{t}-c{i}" for i in range(3)]
            for op in workload(cities, steps=10**6, seed=round_no * 100 + t):
                if stop.is_set() or not client.send(op):
                    return

        threads = [threading.Thread(target=writer, args=(t, models[t])) for t in range(THREADS)]
        for th in threads:
            th.start()
        time.sleep(rng.uniform(0.05, 0.6))
        server.kill9()
        stop.set()
        for th in threads:
            th.join(timeout=30)
        confirmed_total += sum(len(m.confirmed) for m in models)

    final = Server(data, wal_count)
    try:
        actual = read_all(final.url)
        for t, model in enumerate(models):
            check({k: v for k, v in actual.items() if k[0].startswith(f"t{t}-")}, model)
    finally:
        final.stop()
    check_files(data)
    assert confirmed_total > 0
