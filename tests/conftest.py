"""共享 pytest 配置 — 全局隔离仓库 config.yaml。

任何构造真实 MgetApp 的测试都会经由 gui.ConfigManager 读取/写回配置;
若不加隔离, 关窗/保存路径 (_on_close / _save_settings / _persist_modes →
ConfigManager.save()) 会把仓库里的 config.yaml 重写(丢注释、改键序),
污染工作区。

这里用一个 autouse fixture 把 gui.ConfigManager 重定向到每个测试独立的
临时文件, 使全部测试的配置读写都落在 tmp_path, 仓库文件绝对安全。
依赖真实 ConfigManager 默认逻辑的测试仍可子类化 gui_mod.ConfigManager
(继承的 reload/_load_raw/save 行为不变)。
"""
from __future__ import annotations

import sys
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gui as gui_mod  # noqa: E402


def make_tmp_config_class(tmp_path, name="config.yaml"):
    """返回 (子类, cfg_path): 子类仅改 cfg_path, 其余沿用真实逻辑。"""
    cfg_path = tmp_path / name

    class TmpConfigManager(gui_mod.ConfigManager):
        def __init__(self):
            self.cfg_path = cfg_path
            self.data = {}
            self.reload()

    return TmpConfigManager, cfg_path


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """autouse: 让本测试内 gui.ConfigManager 指向临时文件, 不碰仓库。"""
    TmpCM, _ = make_tmp_config_class(tmp_path)
    monkeypatch.setattr(gui_mod, "ConfigManager", TmpCM)
    yield
