from scanner.settings import Settings


def test_defaults(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no .env here
    for var in ("ENABLE_SPANISH", "ENABLE_JAPANESE", "CONVERT_TO_MXN"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert (s.enable_spanish, s.enable_japanese, s.convert_to_mxn) == (False, False, True)
    assert s.languages == ("en",)


def test_reads_env_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ENABLE_SPANISH=true\nENABLE_JAPANESE=1\nCONVERT_TO_MXN=false\n")
    s = Settings()
    assert s.languages == ("en", "es", "ja")
    assert s.convert_to_mxn is False


def test_environment_overrides_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ENABLE_JAPANESE=true\n")
    monkeypatch.setenv("ENABLE_JAPANESE", "false")
    assert Settings().languages == ("en",)
