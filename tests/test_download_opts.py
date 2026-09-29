"""_build_dl_opts audio_format behaviour tests.

``best`` must skip the FFmpegExtractAudio postprocessor entirely (keep
the original stream, no generational transcode), while explicit formats
keep the transcode chain intact.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import mget  # noqa: E402


def _cfg(fmt):
    return {
        "output_dir": "~/Music/mget",
        "audio_format": fmt,
        "audio_quality": 0,
        "proxy": None,
        "embed_metadata": True,
        "embed_thumbnail": False,
    }


def _extract_pps(opts):
    return [p for p in opts["postprocessors"] if p["key"] == "FFmpegExtractAudio"]


class TestBuildDlOpts:
    def test_explicit_format_transcodes(self):
        opts = mget._build_dl_opts(_cfg("mp3"), "youtube")
        (pp,) = _extract_pps(opts)
        assert pp["preferredcodec"] == "mp3"
        assert pp["preferredquality"] == "0"

    def test_best_skips_transcode(self):
        opts = mget._build_dl_opts(_cfg("best"), "youtube")
        assert _extract_pps(opts) == []

    def test_best_keeps_original_stream_format(self):
        opts = mget._build_dl_opts(_cfg("best"), "youtube")
        assert opts["format"] == "bestaudio/best"

    def test_best_still_embeds_metadata(self):
        opts = mget._build_dl_opts(_cfg("best"), "youtube")
        keys = [p["key"] for p in opts["postprocessors"]]
        assert "FFmpegMetadata" in keys

    def test_best_without_metadata_has_empty_postprocessors(self):
        cfg = _cfg("best")
        cfg["embed_metadata"] = False
        opts = mget._build_dl_opts(cfg, "youtube")
        assert opts["postprocessors"] == []
