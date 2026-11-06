from helpers import clip, clipdata, policy

from magicvideo.qc.runner import _partner_heard


def test_couple_speech_counts_as_partner_heard():
    p = policy()
    couple = clipdata(clip(duration=20), [(5.0, 5.4, "hi")], speakers=["COUPLE"])
    other = clipdata(clip(duration=20), [(5.0, 5.4, "hi")], speakers=["OTHER"])
    assert _partner_heard(couple, 5.0, 0.5, p) is True
    assert _partner_heard(other, 5.0, 0.5, p) is False
    assert _partner_heard(None, 5.0, 0.5, p) is False
