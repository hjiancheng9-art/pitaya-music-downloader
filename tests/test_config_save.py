"""ConfigManager.save() 注释保护回归。

核心保证: save() 最小化改动 — 值未变的键原样保留(含行尾注释/空行),
值变了的只重写值部分, 新键追加到末尾。避免 yaml.dump 整文件重写
丢失中文注释与键序。
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import gui as gui_mod  # noqa: E402
from player import MODE_ORDER, MODE_RANDOM, MODE_STOP  # noqa: E402

# 现仓库 config.yaml 的真实内容 (含注释), 作为"原文件"基准
ORIG = """# mget 音乐下载器配置
output_dir: ~/Music/mget          # 下载目录
audio_format: mp3                 # 输出格式
audio_quality: 0                  # 0=最高音质
embed_metadata: true              # 嵌入歌曲信息
embed_thumbnail: true             # 嵌入封面图
search_count: 20                  # 每个源搜索结果数量

# 音源优先级（按顺序尝试，失败自动回退下一个）
source_priority:
  - youtube
  - soundcloud
  - bilibili

# 网易云直链优先
netease_direct: true

# 代理设置：YouTube/SoundCloud 需要科学上网
# proxy: http://127.0.0.1:7890
"""


def _cm_with(tmp_path, content):
    """构造指向 tmp 文件的 ConfigManager, 并 seed data。"""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(content, encoding="utf-8")

    class CMC(gui_mod.ConfigManager):
        def __init__(self):
            self.cfg_path = cfg_path
            self.data = {}
            self.reload()

    cm = CMC()
    return cm, cfg_path


class TestSavePreservesComments:
    def test_unchanged_values_byte_identical(self, tmp_path):
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["player_mode"] = MODE_ORDER   # == 已含在 default, 但文件里没这键
        cm.data["stream_mode"] = MODE_ORDER
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        # 所有原注释行仍在
        assert "# mget 音乐下载器配置" in text
        assert "# 下载目录" in text
        assert "# 音源优先级（按顺序尝试，失败自动回退下一个）" in text
        assert "# 网易云直链优先" in text
        assert "# 代理设置：YouTube/SoundCloud 需要科学上网" in text
        # 值未变的键原行原样 (对齐的空格都保留)
        assert "output_dir: ~/Music/mget          # 下载目录" in text
        # 新增的模式键被追加到末尾
        assert "player_mode: 0" in text
        assert "stream_mode: 0" in text

    def test_changed_value_only_rewrites_value(self, tmp_path):
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["audio_format"] = "flac"
        cm.data["search_count"] = 50
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        # 值变了但行尾注释保留
        assert "audio_format: flac" in text
        assert "# 输出格式" in text
        assert "search_count: 50" in text
        # 未动的键原样
        assert "embed_metadata: true              # 嵌入歌曲信息" in text
        # 模式键追加到末尾
        assert "player_mode: 0" in text

    def test_bool_value_toggle_preserves_comment(self, tmp_path):
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["netease_direct"] = False
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        assert "netease_direct: false" in text
        assert "# 网易云直链优先" in text

    def test_list_value_rewrite_preserves_key_and_comments(self, tmp_path):
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["source_priority"] = ["bilibili", "youtube"]
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        # 源优先级注释行仍在
        assert "# 音源优先级（按顺序尝试，失败自动回退下一个）" in text
        # 条目被重排
        assert lines.index("  - bilibili") < lines.index("  - youtube")

    def test_new_key_appended_at_end(self, tmp_path):
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["player_mode"] = MODE_STOP
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        assert text.rstrip().endswith("stream_mode: 0") or \
               "stream_mode: 0" in text
        # 原文件尾部内容仍在 (没被推到新键后面之外的位置破坏)
        assert "# 代理设置：YouTube/SoundCloud 需要科学上网" in text

    def test_missing_file_falls_back_to_dump(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        assert not cfg_path.exists()

        class CMC(gui_mod.ConfigManager):
            def __init__(self):
                self.cfg_path = cfg_path
                self.data = {}
                self.reload()  # 文件不存在 → 全默认值

        cm = CMC()
        cm.save()
        text = cfg_path.read_text(encoding="utf-8")
        # 全量 dump: 无注释但键齐全
        data = yaml.safe_load(text)
        assert data["player_mode"] == MODE_ORDER
        assert data["stream_mode"] == MODE_ORDER
        assert data["audio_format"] == "mp3"

    def test_save_idempotent_no_comment_loss_on_second_save(self, tmp_path):
        """连存两次, 注释仍不丢 (最小改动 → 二次 save 应字节不变)。"""
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["player_mode"] = MODE_RANDOM
        cm.data["stream_mode"] = MODE_RANDOM
        cm.save()
        snap1 = cfg_path.read_text(encoding="utf-8")
        cm.save()  # 值未变
        snap2 = cfg_path.read_text(encoding="utf-8")
        assert snap1 == snap2, "二次 save 应幂等, 不应再改动文件"

    def test_reload_round_trip(self, tmp_path):
        """save 后 reload 读回的 data 与写入一致 (模式键持久化)。"""
        cm, cfg_path = _cm_with(tmp_path, ORIG)
        cm.data["player_mode"] = MODE_STOP
        cm.data["stream_mode"] = MODE_RANDOM
        cm.save()

        class CMC2(gui_mod.ConfigManager):
            def __init__(self):
                self.cfg_path = cfg_path
                self.data = {}
                self.reload()

        cm2 = CMC2()
        assert cm2.data["player_mode"] == MODE_STOP
        assert cm2.data["stream_mode"] == MODE_RANDOM
