"""仓库 config.yaml 写入隔离回归 (Tk-free, 确定性)。

conftest.isolated_config (autouse) 已把 gui.ConfigManager 指到临时文件;
本文件从“写”这一侧证明: 即便走完持久化/保存路径, 仓库 config.yaml
的 md5 也绝不变, 且写入确实落到了临时文件而非仓库路径。
"""
from __future__ import annotations

import sys
import os
import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gui as gui_mod  # noqa: E402

REPO_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else None


@pytest.fixture
def repo_config_md5():
    """测试前快照仓库 config.yaml 的 md5。"""
    return _md5(REPO_CONFIG)


def _shell():
    """MgetApp 壳: 真实 (被 autouse 隔离到临时的) ConfigManager + stub 引擎。"""
    app = gui_mod.MgetApp.__new__(gui_mod.MgetApp)
    app.cfg = gui_mod.ConfigManager()  # autouse → 指向 tmp_path/config.yaml
    app.player = MagicMock()
    app.player.mode = gui_mod.MODE_STOP
    app._stream_mode = gui_mod.MODE_REPEAT
    return app


class TestConfigWriteIsolation:
    def test_persist_modes_writes_temp_not_repo(self, tmp_path, repo_config_md5):
        app = _shell()
        app._persist_modes()  # 走 关窗前 的持久化路径
        # 仓库文件未被碰
        assert _md5(REPO_CONFIG) == repo_config_md5
        # 写入确实落在临时文件
        assert app.cfg.cfg_path == tmp_path / "config.yaml"
        data = yaml.safe_load(app.cfg.cfg_path.read_text(encoding="utf-8"))
        assert data["player_mode"] == gui_mod.MODE_STOP
        assert data["stream_mode"] == gui_mod.MODE_REPEAT

    def test_config_manager_save_never_targets_repo(self, tmp_path, repo_config_md5):
        cm = gui_mod.ConfigManager()  # autouse → 临时
        assert cm.cfg_path == tmp_path / "config.yaml"
        assert cm.cfg_path != REPO_CONFIG
        cm.data["player_mode"] = gui_mod.MODE_RANDOM
        cm.data["stream_mode"] = gui_mod.MODE_STOP
        cm.save()
        assert _md5(REPO_CONFIG) == repo_config_md5

    def test_repo_config_md5_stable_across_many_saves(self, repo_config_md5):
        """连续多次持久化不同模式, 仓库文件始终不变。"""
        for mode in (gui_mod.MODE_ORDER, gui_mod.MODE_RANDOM,
                     gui_mod.MODE_REPEAT, gui_mod.MODE_STOP):
            app = _shell()
            app._stream_mode = mode
            app._persist_modes()
        assert _md5(REPO_CONFIG) == repo_config_md5

    def test_repo_config_md5_not_none(self, repo_config_md5):
        """canary: 仓库 config.yaml 确实存在且可读, md5 快照有效。"""
        assert REPO_CONFIG.exists()
        assert repo_config_md5 is not None
