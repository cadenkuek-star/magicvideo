import datetime as dt

import numpy as np

from magicvideo.ingest import detect_camera, filename_time, insta360_key, looks_dual_fisheye, parse_qt_date, to_local_naive


def test_filename_times():
    assert filename_time("DJI_20260419083601_0001_D.MP4") == dt.datetime(2026, 4, 19, 8, 36, 1)
    assert filename_time("VID_20260419_120000_00_001.insv") == dt.datetime(2026, 4, 19, 12, 0, 0)
    assert filename_time("LRV_20260419_120000_11_001.lrv") == dt.datetime(2026, 4, 19, 12, 0, 0)
    assert filename_time("PXL_20260419_120000123.mp4") == dt.datetime(2026, 4, 19, 12, 0, 0)
    assert filename_time("C0001.MP4") is None


def test_insta360_grouping_key():
    assert insta360_key("VID_20260419_120000_00_001.insv") == ("20260419_120000_001", "vid")
    assert insta360_key("LRV_20260419_120000_11_001.lrv") == ("20260419_120000_001", "lrv")
    assert insta360_key("VID_20260419_120000_10_001.insv")[0] == "20260419_120000_001"


def test_camera_kinds():
    assert detect_camera("DJI_20260419083601_0001_D.MP4", ".mp4", {"encoder": "DJI Osmo Pocket 4P"})["kind"] == "gimbal"
    assert detect_camera("DJI_20260419083601_0001_D.MP4", ".mp4", {"model": "DJI Osmo Nano"})["kind"] == "action"
    assert detect_camera("x.mp4", ".mp4", {"encoder": "DJI something"})["make"] == "DJI"
    assert detect_camera("VID_20260419_120000_00_001.insv", ".insv", {})["kind"] == "360"
    assert detect_camera("IMG_1.MOV", ".mov", {"com.apple.quicktime.make": "Apple"})["kind"] == "phone"
    assert detect_camera("C0001.MP4", ".mp4", {})["kind"] == "unknown"


def test_dual_fisheye_heuristic():
    h, w = 256, 512
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w), np.uint8)
    for cx in (128, 384):
        img[(xx - cx) ** 2 + (yy - 128) ** 2 < 120 ** 2] = 150
    assert looks_dual_fisheye(img)
    equirect = np.full((h, w), 120, np.uint8)
    assert not looks_dual_fisheye(equirect)


def test_qt_dates_and_timezone():
    t = parse_qt_date("2026-04-19T08:36:01+0900")
    assert t.utcoffset() == dt.timedelta(hours=9)
    assert to_local_naive(t, None) == dt.datetime(2026, 4, 19, 8, 36, 1)
    utc = parse_qt_date("2026-04-18T23:36:01Z")
    assert to_local_naive(utc, "Asia/Seoul") == dt.datetime(2026, 4, 19, 8, 36, 1)
