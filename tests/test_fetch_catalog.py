import json
from datetime import date
from types import SimpleNamespace

import pytest

import scripts.fetch_catalog as fc


class FakeImage:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


class FakeCard:
    def __init__(self, cid, local_id, name, has_image=True):
        self.id, self.localId, self.name = cid, local_id, name
        self.image = f"https://example/{cid}" if has_image else None
        self.downloads = 0

    def get_image(self, quality, ext):
        assert (quality, ext) == ("high", "webp")
        self.downloads += 1
        return FakeImage(b"img-" + self.id.encode())


class FakeSetEndpoint:
    def __init__(self, sets):
        self.sets = sets

    def getSync(self, set_id):
        return self.sets[set_id]


@pytest.fixture
def fake_sdk(monkeypatch):
    cards = [FakeCard("s1-001", "001", "A"), FakeCard("s1-002", "002", "B"), FakeCard("s1-003", "003", "C", False)]
    sets = {"s1": SimpleNamespace(id="s1", name="Set One", cards=cards)}
    sdk = SimpleNamespace(set=FakeSetEndpoint(sets))
    monkeypatch.setattr(fc, "TCGdex", lambda lang: sdk)
    return cards


def test_download_and_resume(tmp_path, monkeypatch, fake_sdk):
    monkeypatch.setattr(fc, "ROOT", tmp_path)
    data = tmp_path / "data"
    assert fc.main(["--sets", "s1", "--data-dir", str(data), "--rate", "0"]) == 0

    rows = [json.loads(l) for l in (data / "catalog_en.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["s1-001", "s1-002"]  # card without image skipped
    assert rows[0] == {
        "id": "s1-001", "name": "A", "set": "s1", "set_name": "Set One", "number": "001",
        "language": "en", "image_path": "data/images/en/s1/s1-001.webp",
    }
    assert (tmp_path / rows[0]["image_path"]).read_bytes() == b"img-s1-001"

    # Simulate an interrupted run: second image lost, plus a half-written line.
    (tmp_path / rows[1]["image_path"]).unlink()
    with (data / "catalog_en.jsonl").open("a") as f:
        f.write('{"id": "s1-00')
    assert fc.main(["--sets", "s1", "--data-dir", str(data), "--rate", "0"]) == 0

    assert fake_sdk[0].downloads == 1  # not downloaded again
    assert fake_sdk[1].downloads == 2  # re-downloaded
    rows = [json.loads(l) for l in (data / "catalog_en.jsonl").read_text().splitlines()]
    assert sorted(r["id"] for r in rows) == ["s1-001", "s1-002"]


def test_select_sets_filters_by_date_and_pocket():
    info = {
        "sv06": {"releaseDate": "2024-05-24", "serie": "sv"},
        "sv01": {"releaseDate": "2023-03-31", "serie": "sv"},
        "A1": {"releaseDate": "2024-10-30", "serie": "tcgp"},
        "me01": {"releaseDate": "2025-09-26", "serie": "me"},
    }
    assert fc.select_sets(info, date(2023, 10, 14)) == ["sv06", "me01"]


def test_with_retries_backs_off_on_429(monkeypatch):
    from urllib.error import HTTPError

    sleeps = []
    monkeypatch.setattr(fc.time, "sleep", sleeps.append)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise HTTPError("u", 429, "slow down", {}, None)
        return "ok"

    assert fc.with_retries(flaky, fc.RateLimiter(0)) == "ok"
    assert sleeps == [2, 4]
