"""Netease Cloud Music integration tests.

Offline tests mock ``requests.get`` so they run without network.

The live smoke test hits the real Netease API on every run but is
non-blocking: if the API is unreachable or returns nothing it emits a
warning and skips instead of failing. Set SKIP_LIVE=1 to opt out
entirely (e.g. in an offline CI sandbox).
"""

from __future__ import annotations

import os
import sys
import time
import warnings

import pytest

# Make the project root importable regardless of the pytest rootdir.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mget  # noqa: E402


# --------------------------------------------------------------------------- #
# Fake HTTP plumbing
# --------------------------------------------------------------------------- #
class _FakeJsonResp:
    """Minimal stand-in for a requests.Response used by netease_search."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeStreamResp:
    """Minimal stand-in for a streaming requests.Response (download_netease)."""

    def __init__(self, status_code=200, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)

    def iter_content(self, chunk_size=8192):  # noqa: ARG002 - signature parity
        yield from self._chunks


class _SlowStreamResp(_FakeStreamResp):
    """Stream response that stalls mid-download to exercise the speed window.

    ``download_netease`` only samples speed when elapsed time in a chunk
    iteration reaches 0.3s; without a stall the speed string stays empty.
    """

    def __init__(self, *args, sleep_after=0, delay=0.0, **kwargs):
        super().__init__(*args, **kwargs)
        self._sleep_after = sleep_after
        self._delay = delay

    def iter_content(self, chunk_size=8192):  # signature parity with requests
        for i, chunk in enumerate(self._chunks):
            if self._delay and i == self._sleep_after:
                time.sleep(self._delay)
            yield chunk


# --------------------------------------------------------------------------- #
# netease_search
# --------------------------------------------------------------------------- #
def test_netease_search_parses_results(monkeypatch):
    payload = {
        "code": 200,
        "result": {
            "songs": [
                {
                    "name": "晴天",
                    "artists": [{"name": "周杰伦"}],
                    "album": {"name": "叶惠美"},
                    "duration": 269000,
                    "id": 186016,
                    "fee": 0,
                }
            ]
        },
    }
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: _FakeJsonResp(payload))

    res = mget.netease_search("晴天", limit=1)

    assert len(res) == 1
    song = res[0]
    assert song["name"] == "晴天"
    assert song["artists"] == "周杰伦"
    assert song["album"] == "叶惠美"
    assert song["duration"] == pytest.approx(269.0)
    assert song["id"] == 186016
    assert song["fee"] == 0
    assert song["search_query"] == "晴天 周杰伦"
    assert song["download_url"] == "https://music.163.com/song/media/outer/url?id=186016.mp3"
    assert song["preview_url"] == song["download_url"]


def test_netease_search_multiple_artists_joined(monkeypatch):
    payload = {
        "code": 200,
        "result": {"songs": [{"name": "x", "artists": [{"name": "A"}, {"name": "B"}], "id": 1}]},
    }
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: _FakeJsonResp(payload))
    res = mget.netease_search("x")
    assert res[0]["artists"] == "A / B"


def test_netease_search_non_200_returns_empty(monkeypatch):
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: _FakeJsonResp({"code": 400}))
    assert mget.netease_search("x") == []


def test_netease_search_exception_returns_empty(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(mget.requests, "get", _boom)
    assert mget.netease_search("x") == []


# --------------------------------------------------------------------------- #
# display_netease_results
# --------------------------------------------------------------------------- #
def test_display_netease_results_marks_vip(capsys):
    results = [
        {"id": 1, "fee": 1, "name": "VIP Song", "artists": "A",
         "album": "X", "duration": 200.0},
        {"id": 2, "fee": 0, "name": "Free Song", "artists": "B",
         "album": "", "duration": 180.0},
    ]
    mget.display_netease_results(results, "kw")
    out = capsys.readouterr().out
    assert "VIP Song 【VIP】" in out
    assert out.count("【VIP】") == 1
    assert "Free Song" in out


# --------------------------------------------------------------------------- #
# download_netease
# --------------------------------------------------------------------------- #
def _cfg(tmp_path):
    return {"output_dir": str(tmp_path)}


def test_download_netease_missing_id(tmp_path):
    ok, err = mget.download_netease({"name": "n", "artists": "a"}, _cfg(tmp_path))
    assert ok is False
    assert "ID" in err


def test_download_netease_vip_rejected(tmp_path):
    song = {"id": 1, "fee": 1, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(song, _cfg(tmp_path))
    assert ok is False
    assert "VIP" in err


def test_download_netease_403(tmp_path, monkeypatch):
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: _FakeStreamResp(status_code=403))
    song = {"id": 1, "fee": 0, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(song, _cfg(tmp_path))
    assert ok is False
    assert "403" in err


def test_download_netease_html_error_page(tmp_path, monkeypatch):
    resp = _FakeStreamResp(status_code=200, headers={"content-type": "text/html; charset=utf-8"})
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: resp)
    song = {"id": 1, "fee": 0, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(song, _cfg(tmp_path))
    assert ok is False
    assert "链接无效" in err


def test_download_netease_success(tmp_path, monkeypatch):
    resp = _FakeStreamResp(
        status_code=200,
        headers={"content-type": "audio/mpeg", "content-length": "10"},
        chunks=[b"12345", b"67890"],
    )
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: resp)

    seen = []
    song = {"id": 42, "fee": 0, "name": "Song/Name", "artists": "Artist"}
    ok, err = mget.download_netease(
        song, _cfg(tmp_path), progress_callback=lambda pct, spd: seen.append(pct)
    )

    assert ok is True
    assert err == ""
    # Filename sanitised: "/" -> "_"
    out = os.path.join(str(tmp_path), "Song_Name-Artist.mp3")
    assert os.path.exists(out)
    assert open(out, "rb").read() == b"1234567890"
    assert seen  # progress callback fired


def test_download_netease_progress_reports_monotonic_to_100(tmp_path, monkeypatch):
    """Progress callback must climb monotonically and land exactly on 100.

    Guards the GUI download-bar contract: gui._poll_download writes the
    callback's pct straight into ttk.Progressbar.value, so a non-monotonic
    or non-terminal sequence would render a bar that jumps or never fills.
    """
    chunk = b"\x00" * 8192
    chunks = [chunk] * 10
    total = len(chunk) * len(chunks)
    resp = _SlowStreamResp(
        status_code=200,
        headers={"content-type": "audio/mpeg", "content-length": str(total)},
        chunks=chunks,
        sleep_after=1,
        delay=0.31,  # force one speed-sampling window (dt >= 0.3)
    )
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: resp)

    seen = []
    song = {"id": 7, "fee": 0, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(
        song, _cfg(tmp_path), progress_callback=lambda pct, spd: seen.append((pct, spd))
    )

    assert ok is True, err
    pcts = [p for p, _ in seen]
    assert pcts, "progress callback never fired"
    assert pcts == sorted(pcts)  # monotonic non-decreasing
    assert pcts[0] > 0
    assert pcts[-1] == 100  # terminal 100 so the bar reaches full
    assert all(0 <= p <= 100 for p in pcts)
    assert any(spd for _, spd in seen)  # speed string populated


def test_download_netease_progress_unknown_total_is_minus_one(tmp_path, monkeypatch):
    """Without content-length pct must be -1 (unknown), never a bogus number.

    The GUI maps unknown to an indeterminate bar via max(pct, 0); keeping -1
    as the source of truth lets it tell "unknown size" apart from "0%".
    """
    resp = _FakeStreamResp(
        status_code=200,
        headers={"content-type": "audio/mpeg"},  # no content-length
        chunks=[b"abc", b"def"],
    )
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: resp)

    seen = []
    song = {"id": 9, "fee": 0, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(
        song, _cfg(tmp_path), progress_callback=lambda pct, spd: seen.append(pct)
    )

    assert ok is True, err
    assert seen == [-1, -1]


def test_download_netease_empty_body_fails(tmp_path, monkeypatch):
    resp = _FakeStreamResp(status_code=200, headers={"content-type": "audio/mpeg"}, chunks=[])
    monkeypatch.setattr(mget.requests, "get", lambda *a, **k: resp)
    song = {"id": 1, "fee": 0, "name": "n", "artists": "a"}
    ok, err = mget.download_netease(song, _cfg(tmp_path))
    assert ok is False
    assert "空" in err


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_parse_multi_select_forms():
    assert mget.parse_multi_select("1,3,5", 6) == [0, 2, 4]
    assert mget.parse_multi_select("1-3", 6) == [0, 1, 2]
    assert mget.parse_multi_select("all", 4) == [0, 1, 2, 3]
    assert mget.parse_multi_select("q", 4) is None
    assert mget.parse_multi_select("1，2", 4) == [0, 1]  # full-width comma


def test_fmt_duration():
    # Matches mget.fmt_duration: "M:SS" under an hour, "H:MM:SS" beyond.
    assert mget.fmt_duration(269) == "4:29"
    assert mget.fmt_duration(0) == "0:00"
    assert mget.fmt_duration(3661) == "1:01:01"


# --------------------------------------------------------------------------- #
# Live smoke test — runs every time, never blocks the build.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.environ.get("SKIP_LIVE") == "1", reason="SKIP_LIVE=1 set")
def test_netease_search_live():
    """Hit the real API. Warn + skip (non-blocking) when it is unavailable.

    A green run guarantees the live contract still holds. An unavailable
    API surfaces as a warning + skip rather than a failure, so transient
    network issues or rate limiting never break the regression.
    """
    try:
        res = mget.netease_search("周杰伦", limit=3)
    except Exception as exc:  # defensive: netease_search already swallows errors
        warnings.warn(f"live Netease search raised: {exc}", stacklevel=1)
        pytest.skip("live API unavailable")

    if not res:
        warnings.warn(
            "live Netease API returned no results "
            "(network down / rate-limited / API changed)",
            stacklevel=1,
        )
        pytest.skip("live API returned empty")

    song = res[0]
    assert set(song) >= {
        "name", "artists", "album", "duration",
        "id", "fee", "search_query", "preview_url", "download_url",
    }
    assert song["id"]
    assert song["download_url"].endswith(f"id={song['id']}.mp3")
