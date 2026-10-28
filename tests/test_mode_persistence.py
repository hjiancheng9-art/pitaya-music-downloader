"""播放模式持久化集成测试 (本地播放器 + 在线曲库)。

三层覆盖:
1. TestConfigManagerDefaults — 配置层: 缺省键 + save/重载往返 (无 Tk)
2. TestRestorePersistLogic — MgetApp 逻辑层: _restore_modes / _persist_modes
   走真实 TmpConfigManager 读写临时文件, 引擎用 stub (无 Tk)
3. TestFullAppRoundTrip — 全量集成: 真实 tk 窗口, 启动恢复 → 按钮文案
   同步 → 切换模式 → 持久化 → 重新读配置验证

同一 pytest 进程内销毁过 Tk root 后再建 Tk 会偶发 Tcl 读库失败,
故全文件仅保留一个 Tk 用例; 逻辑验证全部放无 Tk 层。
"""
from __future__ import annotations

import sys
import os
from unittest.mock import patch, MagicMock

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gui as gui_mod  # noqa: E402
from player import MODE_ORDER, MODE_RANDOM, MODE_REPEAT, MODE_STOP  # noqa: E402


def _tmp_config_class(tmp_path, cfg_name="config.yaml"):
    """ConfigManager 子类: 读写 tmp_path/cfg_name, 其余逻辑不变。"""
    cfg_path = tmp_path / cfg_name

    class TmpConfigManager(gui_mod.ConfigManager):
        def __init__(self):
            self.cfg_path = cfg_path
            self.data = {}
            self.reload()

    return TmpConfigManager, cfg_path


def _seed(cfg_path, out_dir, **extra):
    base = {"output_dir": str(out_dir)}
    base.update(extra)
    cfg_path.write_text(yaml.dump(base), encoding="utf-8")


class TestConfigManagerDefaults:
    """配置层: 缺省值与 save 往返。"""

    def test_load_raw_defaults_when_file_missing(self, tmp_path):
        TmpCM, _ = _tmp_config_class(tmp_path)
        cm = TmpCM()  # 不预置文件
        assert cm.data["player_mode"] == MODE_ORDER
        assert cm.data["stream_mode"] == MODE_ORDER

    def test_save_reload_round_trip(self, tmp_path):
        TmpCM, _ = _tmp_config_class(tmp_path)
        cm = TmpCM()
        cm.data["player_mode"] = MODE_REPEAT
        cm.data["stream_mode"] = MODE_STOP
        cm.save()

        cm2 = TmpCM()
        assert cm2.data["player_mode"] == MODE_REPEAT
        assert cm2.data["stream_mode"] == MODE_STOP

    def test_old_config_without_mode_keys_gains_defaults(self, tmp_path):
        """旧版 config.yaml 没有模式键 → 读取时补默认值, 不丢原字段。"""
        TmpCM, cfg_path = _tmp_config_class(tmp_path)
        out = tmp_path / "out"
        _seed(cfg_path, out, audio_format="flac")
        cm = TmpCM()
        assert cm.data["player_mode"] == MODE_ORDER
        assert cm.data["stream_mode"] == MODE_ORDER
        assert cm.data["audio_format"] == "flac"


def _make_shell(tmp_path, out_dir, seed_extra=None):
    """无 Tk 的 MgetApp 壳: 真实 TmpConfigManager + stub 引擎。

    同一 tmp_path 两次调用共享同一配置文件, 即模拟两次启动。
    seed_extra=None 表示不写文件 (读已有内容)。
    """
    TmpCM, cfg_path = _tmp_config_class(tmp_path)
    if seed_extra is not None:
        _seed(cfg_path, out_dir, **seed_extra)
    app = gui_mod.MgetApp.__new__(gui_mod.MgetApp)
    app.cfg = TmpCM()
    app.cfg_path = cfg_path
    app._stream_mode = MODE_ORDER
    app.player = MagicMock()  # 不真初始化 pygame
    return app


class TestRestorePersistLogic:
    """_restore_modes / _persist_modes 逻辑层 (真实配置读写, 无 Tk)。"""

    def test_restore_missing_keys_default_to_order(self, tmp_path):
        out = tmp_path / "out"; out.mkdir()
        app = _make_shell(tmp_path, out, seed_extra={})
        app._restore_modes()
        app.player.set_mode.assert_called_once_with(MODE_ORDER)
        assert app._stream_mode == MODE_ORDER

    def test_restore_saved_modes(self, tmp_path):
        out = tmp_path / "out"; out.mkdir()
        app = _make_shell(tmp_path, out, seed_extra={
            "player_mode": MODE_REPEAT, "stream_mode": MODE_STOP})
        app._restore_modes()
        app.player.set_mode.assert_called_once_with(MODE_REPEAT)
        assert app._stream_mode == MODE_STOP

    def test_persist_writes_engines_state_to_config(self, tmp_path):
        out = tmp_path / "out"; out.mkdir()
        app = _make_shell(tmp_path, out, seed_extra={})
        app.player.mode = MODE_RANDOM
        app._stream_mode = MODE_REPEAT
        app._persist_modes()

        assert app.cfg.data["player_mode"] == MODE_RANDOM
        assert app.cfg.data["stream_mode"] == MODE_REPEAT
        data = yaml.safe_load(app.cfg_path.read_text(encoding="utf-8"))
        assert data["player_mode"] == MODE_RANDOM
        assert data["stream_mode"] == MODE_REPEAT

    def test_restore_reads_file_written_by_persist(self, tmp_path):
        """同一配置文件模拟两次启动: 第一次持久化, 第二次读回。"""
        out = tmp_path / "out"; out.mkdir()
        a1 = _make_shell(tmp_path, out, seed_extra={})
        a1.player.mode = MODE_STOP
        a1._stream_mode = MODE_RANDOM
        a1._persist_modes()

        a2 = _make_shell(tmp_path, out)  # seed_extra=None: 读已有文件
        a2._restore_modes()
        a2.player.set_mode.assert_called_once_with(MODE_STOP)
        assert a2._stream_mode == MODE_RANDOM


class TestFullAppRoundTrip:
    """全量集成: 真实 tk 窗口 + 真实引擎 + 按钮文案同步 (唯一 Tk 用例)。"""

    def test_start_restore_buttons_persist(self, tmp_path):
        out = tmp_path / "out"; out.mkdir()
        TmpCM, cfg_path = _tmp_config_class(tmp_path)
        _seed(cfg_path, out, player_mode=MODE_REPEAT, stream_mode=MODE_STOP)

        import tkinter as tk
        root = tk.Tk()
        with patch.object(gui_mod, "ConfigManager", TmpCM), \
             patch.object(gui_mod, "find_best_proxy", return_value=(None, True)):
            app = gui_mod.MgetApp(root)
            # 启动恢复: 引擎状态 + 按钮文案/颜色
            assert app.player.mode == MODE_REPEAT
            assert app._stream_mode == MODE_STOP
            assert "单曲" in app._player_mode_btn.cget("text")
            assert "一遍" in app.stream_mode_btn.cget("text")
            assert app.stream_repeat_btn.cget("fg") == gui_mod.CLR["text3"]

            # 切模式 → 触发关窗前持久化 (与 _on_close 同路径)
            app.player.set_mode(MODE_STOP)
            app._stream_mode = MODE_RANDOM
            app._persist_modes()
        root.destroy()

        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert data["player_mode"] == MODE_STOP
        assert data["stream_mode"] == MODE_RANDOM
