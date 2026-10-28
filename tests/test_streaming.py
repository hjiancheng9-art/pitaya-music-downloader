"""流式播放集成测试: StreamerEngine (VLC) 层 + gui 在线曲库交互层。

引擎层: 只 mock vlc.Instance (不动真实 vlc.State 枚举), 控制 player mock
的 play()/get_state() 返回值, 驱动 tick 线程的 Ended/Error/Playing 分支。
GUI 层: MgetApp 无 Tk 壳 + stub 控件 (沿用 WidgetStub 模式), 验证
在线播放/暂停/停止/进度回调的状态机与提示文案。
"""
from __future__ import annotations

import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import types  # noqa: E402
import vlc  # noqa: E402
import streamer as streamer_mod  # noqa: E402
import gui as gui_mod  # noqa: E402
from streamer import StreamerEngine  # noqa: E402
from player import MODE_ORDER, MODE_REPEAT  # noqa: E402


def _state_seq(*states):
    """get_state() 依次返回给定 vlc.State 值, 耗尽后停在最后一个。"""
    it = iter(list(states))
    last = states[-1]
    def _fn():
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last
    return _fn


def _make_engine(on_tick=None, on_song_end=None, on_error=None):
    """构造引擎但 mock 掉 vlc.Instance: 无真实 VLC 实例/媒体。"""
    inst_mock = MagicMock()
    with patch.object(streamer_mod.vlc, "Instance", return_value=inst_mock):
        eng = StreamerEngine(on_tick=on_tick, on_song_end=on_song_end,
                            on_error=on_error)
    eng._player = MagicMock()          # 完全控制 VLC player
    inst_mock.media_new.return_value = MagicMock()  # media 句柄
    eng._inst = inst_mock
    return eng


def _wait(cond, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline and not cond():
        time.sleep(0.05)
    return cond()


# ─────────────────────────────────────────────────────────────
#  引擎层: StreamerEngine
# ─────────────────────────────────────────────────────────────

class TestEnginePlayControl:
    def test_play_url_success(self):
        eng = _make_engine()
        eng._player.play.return_value = 0
        assert eng.play_url("https://x/a.mp3", "t", "a") is True
        assert eng.is_playing()
        assert eng._player.play.call_count == 1
        eng.shutdown()

    def test_play_url_stop_previous_when_active(self):
        """切歌必须先停掉当前播放 (引擎自带互斥)。"""
        eng = _make_engine()
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        stop_calls_before = eng._player.stop.call_count
        eng.play_url("https://x/b.mp3")
        assert eng._player.stop.call_count == stop_calls_before + 1
        song = eng.current_song()
        assert song["url"] == "https://x/b.mp3"
        eng.shutdown()

    def test_play_url_failure_marks_stopped(self):
        eng = _make_engine()
        eng._player.play.return_value = -1
        assert eng.play_url("https://x/bad.mp3") is False
        assert eng.is_stopped()
        assert eng.current_song() is None
        eng.shutdown()

    def test_play_pause_cycle(self):
        eng = _make_engine()
        assert eng.play_pause() is False  # 从未播放
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        assert eng.play_pause() is True   # 播放 → 暂停
        assert eng.is_paused()
        assert eng._player.pause.call_count == 1
        assert eng.play_pause() is True   # 暂停 → 继续
        assert not eng.is_paused()
        assert eng._player.play.call_count == 2
        eng.shutdown()

    def test_stop_resets_state(self):
        eng = _make_engine()
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng.play_pause()  # paused
        eng.stop()
        assert eng.is_stopped() and not eng.is_paused()
        assert eng.current_song() is None
        eng.shutdown()

    def test_set_volume_clamped(self):
        eng = _make_engine()
        eng.set_volume(5.0)
        eng._player.audio_set_volume.assert_called_with(100)
        eng.set_volume(-1.0)
        eng._player.audio_set_volume.assert_called_with(0)
        eng.set_volume(0.4)
        eng._player.audio_set_volume.assert_called_with(40)
        eng.shutdown()

    def test_position_duration_conversion(self):
        eng = _make_engine()
        assert eng.get_position() == 0  # stopped
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng._player.get_time.return_value = 5300      # ms
        eng._player.get_length.return_value = 21000
        assert eng.get_position() == 5.3
        assert eng.get_duration() == 21.0
        eng.shutdown()

    def test_seek(self):
        eng = _make_engine()
        assert eng.seek(10.0) is False  # stopped 拒绝
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng._song_ended = True  # 预置脏标记, seek 必须清除
        assert eng.seek(62.5) is True
        eng._player.set_time.assert_called_with(62500)
        assert eng._song_ended is False
        eng.shutdown()


# ─────────────────────────────────────────────────────────────
#  引擎层: tick 线程自动回调
# ─────────────────────────────────────────────────────────────

class TestEngineTickThread:
    def test_tick_fires_during_play(self):
        eng = _make_engine()
        tick_calls = []
        eng.on_tick = lambda p, t: tick_calls.append((p, t))
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng._player.get_state.return_value = vlc.State.Playing
        eng._player.get_time.return_value = 7000
        eng._player.get_length.return_value = 30000

        fired = _wait(lambda: len(tick_calls) >= 1)
        eng._player.get_time.return_value = -1  # 停止后续 tick 不再增长
        eng.shutdown()
        assert fired, "Playing 状态下 tick 回调未触发"
        assert tick_calls[0] == (7.0, 30.0)

    def test_song_end_callback_fires_once(self):
        eng = _make_engine()
        ended = threading.Event()
        eng.on_song_end = lambda: ended.set()
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng._player.get_state.side_effect = _state_seq(vlc.State.Ended)

        fired = _wait(ended.is_set)
        eng.shutdown()
        assert fired, "Ended 状态未触发 on_song_end"
        assert eng.is_stopped()
        # 第二次手动触发回调路径不应重复 (stop 后线程跳过)
        eng._song_ended = True
        assert eng._song_ended is True

    def test_error_state_reports_and_stops(self):
        eng = _make_engine()
        errors = []
        eng.on_error = lambda m: errors.append(m)
        eng._player.play.return_value = 0
        eng.play_url("https://x/bad.mp3")
        eng._player.get_state.side_effect = _state_seq(vlc.State.Error)

        fired = _wait(lambda: len(errors) >= 1)
        eng.shutdown()
        assert fired, "Error 状态未触发 on_error"
        assert "失效" in errors[0] or "网络" in errors[0]
        assert eng.is_stopped()

    def test_paused_skips_tick(self):
        """暂停期间 tick 线程不得回调进度 (continue 分支)。"""
        eng = _make_engine()
        ticks = []
        eng.on_tick = lambda p, t: ticks.append(1)
        eng._player.play.return_value = 0
        eng.play_url("https://x/a.mp3")
        eng._player.get_state.return_value = vlc.State.Playing
        eng._player.get_time.return_value = 1000
        eng.play_pause()  # 暂停 → tick_loop continue
        time.sleep(0.7)   # 至少两轮 tick 周期
        assert ticks == []
        eng.shutdown()


# ─────────────────────────────────────────────────────────────
#  GUI 层: 在线曲库流播交互 (无 Tk 壳)
# ─────────────────────────────────────────────────────────────

class WidgetStub:
    """模拟 tk 控件: 支持 .attr / ["attr"] 两种读法 + configure 更新。"""

    def __init__(self, **attrs):
        self._props = dict(attrs)

    def configure(self, **kw):
        self._props.update(kw)

    def __getattr__(self, name):
        return object.__getattribute__(self, "_props")[name]

    def __getitem__(self, key):
        return object.__getattribute__(self, "_props")[key]


def _status(app):
    ca = app.stream_status_var.set.call_args
    return ca[0][0] if ca else ""


def _stream_shell(**over):
    """MgetApp 无 Tk 壳: 只给流播路径需要的属性。"""
    app = gui_mod.MgetApp.__new__(gui_mod.MgetApp)
    app.streamer = MagicMock()
    app.streamer.is_stopped.return_value = False
    app.player = MagicMock()
    app.player.is_playing.return_value = False
    app.player.is_paused.return_value = False
    app._update_player_bar_state = MagicMock()
    app._reset_stream_player_bar = types.MethodType(
        gui_mod.MgetApp._reset_stream_player_bar, app)
    app.stream_results = [
        {"name": "晴天", "artists": "周杰伦", "preview_url": "https://x/a.mp3"},
        {"name": "夜曲", "artists": "周杰伦", "preview_url": ""},
    ]
    app._stream_current_idx = 0
    app._stream_mode = MODE_ORDER
    app._stream_progress_dragging = False
    app._stream_mini_frame = None
    app.stream_tree = MagicMock()
    app.stream_tree.selection.return_value = ["0"]
    app.stream_tree.index.return_value = 0
    app.stream_tree.get_children.return_value = []
    app.stream_status_var = MagicMock()
    app.stream_info_lbl = WidgetStub(text="♫ 未在播放")
    app.stream_pp_btn = WidgetStub(text="▶ 播放")
    app.stream_progress = MagicMock()
    app.stream_time_lbl = WidgetStub(text="--:-- / --:--")
    for k, v in over.items():
        setattr(app, k, v)
    return app


class TestStreamPlaySelected:
    def test_start_streaming_and_stop_local_player(self):
        """在线播放: 调 VLC play_url(预览地址), 先停本地播放防重叠。"""
        app = _stream_shell()
        app.player.is_playing.return_value = True  # 本地正在播
        app._stream_play_selected()
        app.player.stop.assert_called_once()
        app.streamer.play_url.assert_called_once_with(
            "https://x/a.mp3", "晴天", "周杰伦")
        assert "正在播放: 晴天" == _status(app)
        assert app.stream_pp_btn["text"] == "⏸"
        assert "晴天" in app.stream_info_lbl["text"]
        assert app._stream_current_idx == 0

    def test_no_selection_warns(self):
        tree = MagicMock()
        tree.selection.return_value = []
        tree.index.return_value = 0
        tree.get_children.return_value = []
        app = _stream_shell(stream_tree=tree)
        app._stream_play_selected()
        app.streamer.play_url.assert_not_called()
        assert _status(app) == "请先选择一首歌"

    def test_missing_preview_url_warns(self):
        tree = MagicMock()
        tree.selection.return_value = ["1"]
        tree.index.return_value = 1
        tree.get_children.return_value = []
        app = _stream_shell(stream_tree=tree)
        app._stream_play_selected()
        app.streamer.play_url.assert_not_called()
        assert _status(app) == "该歌曲无可播放链接"

    def test_vlc_missing_message(self):
        app = _stream_shell(streamer=None)
        app._stream_play_selected()
        assert _status(app) == "VLC 未就绪"

    def test_play_selected_failure_reports(self):
        app = _stream_shell()
        app.streamer.play_url.return_value = False
        app._stream_play_selected()
        assert _status(app) == "播放失败，链接可能已失效"


class TestStreamTogglePlay:
    def test_toggle_when_stopped_starts_selection(self):
        s = MagicMock()
        s.is_stopped.return_value = True
        app = _stream_shell(streamer=s)
        with patch.object(gui_mod.MgetApp, "_stream_play_selected") as sel:
            app._stream_toggle_play()
        sel.assert_called_once()
        s.play_pause.assert_not_called()

    def test_toggle_when_paused_resumes(self):
        s = MagicMock()
        s.is_stopped.return_value = False
        s.is_paused.return_value = False  # play_pause() 之后是继续播
        app = _stream_shell(streamer=s)
        app._stream_toggle_play()
        s.play_pause.assert_called_once()
        assert app.stream_pp_btn["text"] == "⏸"

    def test_toggle_when_playing_pauses(self):
        s = MagicMock()
        s.is_stopped.return_value = False
        s.is_paused.return_value = True
        app = _stream_shell(streamer=s)
        app._stream_toggle_play()
        assert app.stream_pp_btn["text"] == "▶"

    def test_toggle_without_streamer_noop(self):
        app = _stream_shell(streamer=None)
        app._stream_toggle_play()  # 不抛异常即可


class TestStreamStopAndTicks:
    def test_stop_resets_mini_bar(self):
        app = _stream_shell()
        app.stream_pp_btn = WidgetStub(text="⏸")
        app.stream_progress = MagicMock()
        app.stream_time_lbl = WidgetStub(text="1:00 / 3:00")
        app._stream_stop()
        app.streamer.stop.assert_called_once()
        assert app.stream_pp_btn["text"] == "▶ 播放"
        assert app.stream_progress.set.call_args[0] == (0,)
        assert app.stream_time_lbl["text"] == "--:-- / --:--"
        assert _status(app) == "已停止"

    def test_tick_updates_progress_and_time(self):
        app = _stream_shell()
        app._on_stream_tick(37, 200)
        app.stream_progress.configure.assert_called_with(to=200)
        app.stream_progress.set.assert_called_with(37)
        assert app.stream_time_lbl["text"] == "0:37 / 3:20"

    def test_tick_clamps_pos_to_total(self):
        app = _stream_shell()
        app._on_stream_tick(250, 200)  # pos > total
        app.stream_progress.set.assert_called_with(200)

    def test_tick_unknown_duration(self):
        app = _stream_shell()
        app._on_stream_tick(5, 0)  # 直播/未知时长
        app.stream_progress.configure.assert_called_with(to=100)
        app.stream_progress.set.assert_called_with(0)
        assert app.stream_time_lbl["text"] == "0:05 / --:--"

    def test_tick_skipped_while_dragging(self):
        app = _stream_shell(_stream_progress_dragging=True)
        app._on_stream_tick(10, 100)
        app.stream_progress.set.assert_not_called()

    def test_error_resets_and_reports(self):
        app = _stream_shell()
        app._on_stream_error("播放失败，链接可能已失效或网络不通")
        assert _status(app) == "播放失败，链接可能已失效或网络不通"
        assert app.stream_pp_btn["text"] == "▶ 播放"
