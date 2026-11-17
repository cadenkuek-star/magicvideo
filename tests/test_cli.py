import io

from magicvideo.cli import _utf8_console


def test_utf8_console_handles_japanese():
    raw = io.BytesIO()
    w = io.TextIOWrapper(raw, encoding="cp1252")
    _utf8_console([w])
    w.write("ご視聴“x”")
    w.flush()
    assert raw.getvalue().decode("utf-8") == "ご視聴“x”"
    _utf8_console([object()])      # a stream without reconfigure never raises


def test_main_sets_utf8_console(monkeypatch):
    import pytest

    from magicvideo import cli

    calls = []
    monkeypatch.setattr(cli, "_utf8_console", lambda *a, **k: calls.append(1))
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    assert calls == [1]
