import pytest

from scanner.evaluation import Result, card_id_from_filename, summarize


@pytest.mark.parametrize(
    "name,expected",
    [
        ("sv06-123.jpg", "sv06-123"),
        ("sv06-123_2.JPG", "sv06-123"),
        ("sv06-123 (3).jpeg", "sv06-123"),
        ("sv03.5-151.png", "sv03.5-151"),
        ("sv10.5w-086.webp", "sv10.5w-086"),
        ("svp-085.heic", "svp-085"),
        ("photos/me01-010.jpg", "me01-010"),
    ],
)
def test_card_id_from_filename(name, expected):
    assert card_id_from_filename(name) == expected


def _r(true_id, preds, secs=0.5, cropped=True):
    return Result(f"{true_id}.jpg", true_id, [(p, 1.0) for p in preds], secs, cropped)


def test_rank_is_case_insensitive():
    assert _r("SV06-001", ["x", "sv06-001"]).rank() == 2
    assert _r("a", ["x", "y", "z"]).rank() is None


def test_summarize_topk_and_timing():
    results = [
        _r("a", ["a", "b", "c"], 0.2),
        _r("b", ["a", "b", "c"], 0.4),
        _r("c", ["a", "b", "c"], 0.6, cropped=False),
        _r("d", ["a", "b", "c"], 1.2),
    ]
    s = summarize("m", results)
    assert s.n == 4
    assert s.top1 == pytest.approx(0.25)
    assert s.top3 == pytest.approx(0.75)
    assert s.mean_seconds == pytest.approx(0.6)
    assert s.max_seconds == pytest.approx(1.2)
    assert s.crop_rate == pytest.approx(0.75)
    assert [f.true_id for f in s.failures] == ["b", "c", "d"]


def test_summarize_empty():
    assert summarize("m", []).n == 0


def test_summarize_leaves_gap_cards_out_of_accuracy():
    results = [
        _r("a", ["a", "b", "c"], 0.2),
        _r("b", ["c", "a", "b"], 0.4),
        _r("gap", ["a", "b", "c"], 1.5, cropped=False),
    ]
    s = summarize("m", results, indexed={"A", "b", "c"})
    assert s.n == 2
    assert s.top1 == pytest.approx(0.5)
    assert s.top3 == pytest.approx(1.0)
    assert [f.true_id for f in s.failures] == ["b"]
    assert [g.true_id for g in s.gaps] == ["gap"]
    # Every photo still counts toward timing and crop rate.
    assert s.max_seconds == pytest.approx(1.5)
    assert s.crop_rate == pytest.approx(2 / 3)
