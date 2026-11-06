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
