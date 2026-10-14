from scanner.config import load_rules


def test_rules_file_has_phase1_sections():
    r = load_rules()
    for section in ("crop", "quality", "identification"):
        assert section in r
    assert 1 <= r["crop"]["max_cards"] <= 9
