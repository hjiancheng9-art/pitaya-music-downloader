"""内置精选歌单: 数据形状 + gui 接线。"""
from __future__ import annotations

import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import stream_songs  # noqa: E402
import gui as gui_mod  # noqa: E402


class TestCuratedShape:
    def test_returns_songs(self):
        songs = stream_songs.get_curated()
        assert len(songs) >= 10

    def test_fields_match_search_result_contract(self):
        """每首歌必须带齐 在线表格列 + 播放/下载管线 需要的字段。"""
        required = {"name", "artists", "album", "duration", "id",
                    "fee", "search_query", "preview_url", "download_url"}
        for s in stream_songs.get_curated():
            assert required.issubset(s.keys()), f"缺字段: {required - set(s)}"
            assert s["preview_url"].startswith(
                "https://music.163.com/song/media/outer/url?id=")
            assert s["duration"] > 0
            assert s["id"] and s["name"]

    def test_limit_truncates(self):
        assert len(stream_songs.get_curated(limit=3)) == 3
        assert len(stream_songs.get_curated(limit=999)) == len(stream_songs.CURATED)

    def test_unique_ids(self):
        ids = [s["id"] for s in stream_songs.get_curated()]
        assert len(ids) == len(set(ids)), "存在重复 id"


class TestGuiWiring:
    def test_load_curated_fills_results(self):
        """_load_curated 必须把内置歌单填入 stream_results 与表格。"""
        from unittest.mock import MagicMock
        app = gui_mod.MgetApp.__new__(gui_mod.MgetApp)
        app.stream_results = []
        app.stream_status_var = MagicMock()
        app.stream_tree = MagicMock()
        app._load_curated()
        assert len(app.stream_results) == len(stream_songs.CURATED)
        assert app.stream_tree.insert.call_count == len(stream_songs.CURATED)
        assert "双击在线播放" in app.stream_status_var.set.call_args[0][0]

    def test_load_curated_button_wired(self):
        """精选按钮 command 必须接到 _load_curated。"""
        import tkinter as tk
        root = tk.Tk()
        try:
            app = gui_mod.MgetApp(root)
            if not hasattr(app, "stream_curated_btn"):
                return  # VLC 缺失时 tab 未建, 跳过
            cmd = app.stream_curated_btn.cget("command")
            assert "load_curated" in str(cmd)
        finally:
            root.destroy()
