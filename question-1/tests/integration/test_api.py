"""REST API over a real Database on a temp folder (seam S4). Contract: docs/api-contract.md."""

import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tsdb.api.app import create_app
from tsdb.bootstrap import build_database
from tsdb.config import EngineConfig
from tsdb.errors import FatalStorageError
from tsdb.storage.fileio import OsFileOps

T = 1_730_368_800_000
MINUTE = 60_000


def point(city, ts, value, metric="temperature"):
    return {"metric": metric, "tags": {"city": city, "sensor": "roof"}, "timestamp": ts, "value": value}


@pytest.fixture
def client(tmp_path):
    db = build_database(EngineConfig(data_dir=tmp_path, max_query_series=2))
    with TestClient(create_app(db)) as c:
        yield c
    db.close()


@pytest.fixture
def loaded(client):
    r = client.post("/write", json=[point("Delhi", T, 30.0), point("Delhi", T + MINUTE, 32.0),
                                    point("Mumbai", T, 28.0)])
    assert (r.status_code, r.json()) == (200, {"written": 3})
    return client


def test_write_then_query_raw_and_aggregated(loaded):
    raw = loaded.get("/query", params={"metric": "temperature", "filter": "city=Delhi",
                                       "from": T, "to": T + MINUTE})
    avg = loaded.get("/query", params={"metric": "temperature", "from": T, "to": T + MINUTE,
                                       "agg": "avg", "bucket": "5m"})

    assert raw.status_code == 200
    assert raw.json()["series"] == [{"metric": "temperature", "tags": {"city": "Delhi", "sensor": "roof"},
                                     "points": [[T, 30.0], [T + MINUTE, 32.0]]}]
    assert [(s["tags"]["city"], s["agg"], s["bucket_ms"], s["buckets"]) for s in avg.json()["series"]] == [
        ("Delhi", "avg", 300_000, [[T, 31.0]]), ("Mumbai", "avg", 300_000, [[T, 28.0]])]


def test_series_list_and_delete(loaded):
    assert loaded.get("/series", params={"filter": "city=Mumbai"}).json() == {
        "series": [{"metric": "temperature", "tags": {"city": "Mumbai", "sensor": "roof"}}]}

    r = loaded.delete("/series", params={"metric": "temperature", "filter": "city=Delhi",
                                         "from": T, "to": T})
    left = loaded.get("/query", params={"metric": "temperature", "filter": "city=Delhi",
                                        "from": T, "to": T + MINUTE})

    assert (r.status_code, r.json()) == (200, {"deleted_series": 1})
    assert left.json()["series"][0]["points"] == [[T + MINUTE, 32.0]]


def test_one_bad_point_rejects_the_whole_batch_and_names_its_index(client):
    r = client.post("/write", json=[point("Delhi", T, 30.0), point("Delhi", -5, 31.0)])

    assert r.status_code == 400
    assert r.json()["detail"]["index"] == 1
    assert client.get("/series").json() == {"series": []}          # nothing of the batch was written


@pytest.mark.parametrize("body", [[], {"metric": "x"}, [point("Delhi", T, "hot")],
                                  [{**point("Delhi", T, 1.0), "tags": {"city": 5}}]])
def test_bad_write_bodies_are_400(client, body):
    assert client.post("/write", json=body).status_code == 400


def test_nan_and_infinity_are_rejected(client):
    r = client.post("/write", content=b'[{"metric":"t","tags":{},"timestamp":1,"value":NaN}]',
                    headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_filter_syntax_error_is_400_with_its_position(loaded):
    r = loaded.get("/query", params={"metric": "temperature", "filter": "city=Delhi AND", "from": T, "to": T})

    assert r.status_code == 400
    assert r.json()["detail"]["position"] == 14


@pytest.mark.parametrize("params", [
    {"from": T, "to": T},                                               # metric missing
    {"metric": "temperature", "from": T + 1, "to": T},                  # from > to
    {"metric": "temperature", "from": T, "to": T, "agg": "median"},     # unknown agg
    {"metric": "temperature", "from": T, "to": T, "agg": "avg", "bucket": "5x"},
    {"metric": "temperature", "from": T, "to": T, "bucket": "5m"},      # bucket without agg
])
def test_bad_query_parameters_are_400_with_a_json_error(loaded, params):
    r = loaded.get("/query", params=params)

    assert r.status_code == 400
    assert r.json()["error"]


def test_query_over_the_series_limit_is_400(loaded):
    loaded.post("/write", json=[point("Pune", T, 25.0)])                # 3 series, limit is 2

    r = loaded.get("/query", params={"metric": "temperature", "from": T, "to": T})

    assert r.status_code == 400
    assert "limit" in r.json()["error"]


def test_delete_needs_a_metric_or_a_filter(loaded):
    assert loaded.delete("/series", params={"from": 0, "to": T}).status_code == 400


class SstFsyncFails(OsFileOps):
    """The disk breaks for table files only: the WAL keeps working, the flush thread fails."""

    def __init__(self):
        self._paths = {}

    def open_append(self, path):
        fd = super().open_append(path)
        self._paths[fd] = path
        return fd

    def fsync(self, fd):
        if self._paths.get(fd, Path()).name.endswith(".sst.tmp"):
            raise FatalStorageError("fsync failed: EIO")
        super().fsync(fd)


def test_s5_after_a_failed_flush_writes_get_500_and_nothing_hangs(tmp_path):
    db = build_database(EngineConfig(data_dir=tmp_path, memtable_max_entries=2), files=SstFsyncFails())
    statuses = []

    def keep_writing():
        with TestClient(create_app(db), raise_server_exceptions=False) as c:
            for i in range(20):                        # memtable of 2: the 1st flush fails at once
                statuses.append(c.post("/write", json=[point("Delhi", T + i, float(i))]).status_code)
                if statuses[-1] == 500:
                    return

    writer = threading.Thread(target=keep_writing, daemon=True)
    writer.start()
    writer.join(timeout=10)
    try:
        assert not writer.is_alive(), f"write hung after {statuses}"
        assert statuses[-1] == 500
    finally:
        db.close() if not writer.is_alive() else None
