"""在线曲库 mini 栏「单曲循环开关」行为测试。

用 MgetApp.__new__ 构造空壳实例 + MagicMock 控件, 避免 tkinter 真实窗口。
控件 mock 用 spec_set 绑到 MagicMock 上, 这样 .configure(fg=...) 会真正
把属性写到 mock 上(镜像 tk 控件的 cget/configure 语义)。
"""
from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gui as gui_mod  # noqa: E402
from player import MODE_ORDER, MODE_RANDOM, MODE_REPEAT, MODE_STOP  # noqa: E402


class WidgetStub:
    """模拟 tk 控件: configure(k=v) 会真的更新属性(镜像 cget 语义)。"""

    def __init__(self, **attrs):
        self._props = dict(attrs)

    def configure(self, **kwargs):
        self._props.update(kwargs)

    def __getattr__(self, name):
        # cget 语义: 未显式 set 的属性返回 _props 里的默认值
        props = object.__getattribute__(self, "_props")
        return props[name]


def _cfg_mock(**attrs):
    return WidgetStub(**attrs)


def make_app():
    app = gui_mod.MgetApp.__new__(gui_mod.MgetApp)
    app._stream_mode = MODE_ORDER
    app._stream_current_idx = -1
    app.stream_results = []
    app.stream_status_var = MagicMock()
    app.stream_mode_btn = _cfg_mock(text="🔁 顺序")
    app.stream_repeat_btn = _cfg_mock(fg=gui_mod.CLR["text3"])
    app.stream_pp_btn = _cfg_mock()
    app.stream_progress = MagicMock()
    app.stream_info_lbl = _cfg_mock()
    app.stream_time_lbl = _cfg_mock()
    app.stream_tree = MagicMock()
    app.stream_tree.get_children.return_value = []
    app.streamer = MagicMock()
    return app


def _last_status(app):
    ca = app.stream_status_var.set.call_args
    return ca[0][0] if ca else ""


class TestRepeatOneToggle:
    def test_toggle_on_from_order(self):
        app = make_app()
        app._stream_toggle_repeat_one()
        assert app._stream_mode == MODE_REPEAT
        assert app.stream_repeat_btn.fg == gui_mod.CLR["accent"]
        assert app.stream_mode_btn.text == "🔂 单曲"
        assert _last_status(app) == "单曲循环: 开"

    def test_toggle_off_from_repeat(self):
        app = make_app()
        app._stream_mode = MODE_REPEAT
        app._stream_toggle_repeat_one()
        assert app._stream_mode == MODE_ORDER
        assert app.stream_repeat_btn.fg == gui_mod.CLR["text3"]
        assert app.stream_mode_btn.text == "🔁 顺序"
        assert _last_status(app) == "单曲循环: 关"

    def test_toggle_idempotent_cycle(self):
        app = make_app()
        for expect in (MODE_REPEAT, MODE_ORDER, MODE_REPEAT):
            app._stream_toggle_repeat_one()
            assert app._stream_mode == expect
            expected_fg = gui_mod.CLR["accent"] if expect == MODE_REPEAT else gui_mod.CLR["text3"]
            assert app.stream_repeat_btn.fg == expected_fg

    def test_toggle_from_random_enters_repeat(self):
        app = make_app()
        app._stream_mode = MODE_RANDOM
        app._stream_toggle_repeat_one()
        assert app._stream_mode == MODE_REPEAT
        assert app.stream_repeat_btn.fg == gui_mod.CLR["accent"]

    def test_mode_cycle_syncs_repeat_button_color(self):
        """走模式循环切到/切离单曲时, 开关按钮 fg 必须同步。"""
        app = make_app()
        app._stream_toggle_mode()  # ORDER → RANDOM
        assert app._stream_mode == MODE_RANDOM
        assert app.stream_repeat_btn.fg == gui_mod.CLR["text3"]
        app._stream_toggle_mode()  # RANDOM → REPEAT
        assert app._stream_mode == MODE_REPEAT
        assert app.stream_repeat_btn.fg == gui_mod.CLR["accent"]
        app._stream_toggle_mode()  # REPEAT → STOP
        assert app._stream_mode == MODE_STOP
        assert app.stream_repeat_btn.fg == gui_mod.CLR["text3"]
        app._stream_toggle_mode()  # STOP → ORDER
        assert app._stream_mode == MODE_ORDER
        assert app.stream_repeat_btn.fg == gui_mod.CLR["text3"]


class TestStreamAutoAdvance:
    def test_repeat_mode_replays_on_end(self):
        """单曲循环: 自然结束调 _stream_next(内部重播当前首), 不报播放完毕。"""
        app = make_app()
        app._stream_mode = MODE_REPEAT
        app._stream_current_idx = 2
        app.stream_results = [{"name": f"s{i}"} for i in range(3)]
        next_spied = MagicMock()
        with patch.object(gui_mod.MgetApp, "_stream_next", new=next_spied):
            app._on_stream_end()
        assert next_spied.call_count == 1

    def test_stop_mode_ends_at_last_song(self):
        """一遍: 最后一首自然结束 → 不调 _stream_next, 直接停止并提示播放完毕。"""
        app = make_app()
        app._stream_mode = MODE_STOP
        app._stream_current_idx = 2
        app.stream_results = [{"name": f"s{i}"} for i in range(3)]
        app._reset_stream_player_bar = MagicMock()
        next_spied = MagicMock()
        with patch.object(gui_mod.MgetApp, "_stream_next", new=next_spied):
            app._on_stream_end()
        assert next_spied.call_count == 0
        assert app._reset_stream_player_bar.call_count == 1
        assert _last_status(app) == "列表播放完毕"

    def test_stop_mode_advances_midlist(self):
        """一遍: 列表中间结束 → 调 _stream_next 前进到下一首。"""
        app = make_app()
        app._stream_mode = MODE_STOP
        app._stream_current_idx = 0
        app.stream_results = [{"name": f"s{i}"} for i in range(3)]
        next_spied = MagicMock()
        with patch.object(gui_mod.MgetApp, "_stream_next", new=next_spied):
            app._on_stream_end()
        assert next_spied.call_count == 1


class TestRealUIWiring:
    """真实构造 MgetApp: 验证 mini 栏 🔂 按钮 command 接到开关逻辑。"""

    @patch("gui.find_best_proxy", MagicMock(return_value=(None, True)))
    def test_repeat_one_wired_to_button(self):
        import tkinter as tk
        root = tk.Tk()
        try:
            app = gui_mod.MgetApp(root)
            assert hasattr(app, "stream_repeat_btn"), "mini 栏缺少单曲循环开关按钮"
            # cget('command') 返回 Tcl 包装名 '<id>_stream_toggle_repeat_one'
            cmd = app.stream_repeat_btn.cget("command")
            assert "stream_toggle_repeat_one" in str(cmd)
            # 初始: 顺序模式, 按钮灰色
            assert app._stream_mode == MODE_ORDER
            assert app.stream_repeat_btn.cget("fg") == gui_mod.CLR["text3"]
            app._stream_toggle_repeat_one()
            assert app._stream_mode == MODE_REPEAT
            assert app.stream_repeat_btn.cget("fg") == gui_mod.CLR["accent"]
            app._stream_toggle_repeat_one()
            assert app._stream_mode == MODE_ORDER
        finally:
            root.destroy()
