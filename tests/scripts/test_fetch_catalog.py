import json
from datetime import date

import pytest

import scripts.fetch_catalog as fc


class FakeClient:
    """Stands in for TcgdexClient: one set, the third card has no image."""

    def __init__(self, lang):
        self.lang = lang
        self.cards = [
            {"id": "s1-001", "localId": "001", "name": "A", "image": "https://example/s1-001"},
            {"id": "s1-002", "localId": "002", "name": "B", "image": "https://example/s1-002"},
            {"id": "s1-003", "localId": "003", "name": "C"},
        ]
        self.downloads = {}

    def get_set(self, set_id):
        return {"id": "s1", "name": "Set One", "cards": self.cards}

    def get_image(self, card):
        self.downloads[card["id"]] = self.downloads.get(card["id"], 0) + 1
        return b"img-" + card["id"].encode()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient("en")
    monkeypatch.setattr(fc, "TcgdexClient", lambda lang: client)
    return client


def test_download_and_resume(tmp_path, monkeypatch, fake_client):
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

    assert fake_client.downloads["s1-001"] == 1  # not downloaded again
    assert fake_client.downloads["s1-002"] == 2  # re-downloaded
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


def test_set_info_keeps_printed_code_and_size(tmp_path):
    class Client:
        def list_sets(self):
            return [{"id": "sv01"}]

        def get_set(self, set_id):
            return {"id": "sv01", "name": "Scarlet & Violet", "releaseDate": "2023-03-31",
                    "serie": {"id": "sv"}, "abbreviation": {"official": "SVI"},
                    "cardCount": {"official": 198, "total": 258}}

    info = fc.load_set_dates(Client(), tmp_path / "sets.json", fc.RateLimiter(0))
    assert info["sv01"]["abbreviation"] == "SVI"
    assert info["sv01"]["official_count"] == 198
