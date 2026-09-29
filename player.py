#!/usr/bin/env python3
"""
PlayerEngine — 轻量级音频播放引擎 (pygame.mixer)
支持: 播放/暂停/停止/切歌/进度/音量/播放模式
"""

import os
import time
import random
import threading
from pathlib import Path

import pygame

# 播放模式
MODE_ORDER   = 0   # 顺序播放
MODE_RANDOM  = 1   # 随机播放
MODE_REPEAT  = 2   # 单曲循环


def _probe_stream_info(path):
    """探测音频源流的采样率与声道数，返回 (sample_rate, channels)。
    无法识别时返回 (None, None)，调用方保持现有 mixer 配置不动。"""
    # 1) mutagen：只读元数据头，毫秒级，覆盖 mp3/flac/m4a/ogg/opus
    try:
        from mutagen import File as MutagenFile
        mfile = MutagenFile(str(path))
        info = getattr(mfile, "info", None)
        sr = getattr(info, "sample_rate", None)
        if sr:
            ch = getattr(info, "channels", None) or 2
            return int(sr), (1 if int(ch) == 1 else 2)
    except Exception:
        pass
    # 2) WAV：标准库直接读头
    if str(path).lower().endswith(".wav"):
        try:
            import wave
            with wave.open(str(path), "rb") as w:
                return w.getframerate(), (1 if w.getnchannels() == 1 else 2)
        except Exception:
            pass
    return (None, None)


def _ensure_mixer(frequency, channels):
    """确保 mixer 以源流参数运行，消除 SDL_mixer 的低质量重采样。
    配置一致时不重启；设备拒绝时回退到最通用的 44.1k 立体声。"""
    cur = pygame.mixer.get_init()
    if cur is not None:
        cur_freq, _fmt, cur_ch = cur
        if cur_freq == frequency and cur_ch == channels:
            return
    try:
        pygame.mixer.quit()
        pygame.mixer.pre_init(frequency=frequency, size=-16,
                              channels=channels, buffer=4096)
        pygame.mixer.init()
    except Exception:
        try:
            pygame.mixer.quit()
            pygame.mixer.pre_init(frequency=44100, size=-16,
                                  channels=2, buffer=4096)
            pygame.mixer.init()
        except Exception:
            pass  # 保底：维持现状，加载失败由 play_index 上报


class PlayerEngine:
    """基于 pygame.mixer 的播放引擎，线程安全"""

    def __init__(self, on_tick=None, on_song_end=None):
        """
        on_tick:   callable(cur_pos_sec, total_sec) — 每秒回调进度
        on_song_end: callable() — 歌曲自然结束回调
        """
        # 用 pre_init 设置大缓冲区，防止音频卡顿
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=4096)
        pygame.mixer.init()

        self.playlist = []          # list[dict]: {path, title, artists}
        self.current_index = -1
        self.mode = MODE_ORDER
        self.volume = 0.8
        self._paused = False
        self._stopped = True
        self._song_ended = False   # 防止 on_song_end 重复触发
        self._cached_duration = 0  # 缓存当前歌曲时长，避免每次 tick 重建 Sound 对象
        # seek 偏移追踪：pygame 的 get_pos() 不计入 set_pos() 的偏移量，
        # 拖动进度条后必须自行换算真实位置
        self._seek_base = 0.0
        self._seek_clock = 0.0

        self.on_tick = on_tick
        self.on_song_end = on_song_end

        self._lock = threading.Lock()
        self._tick_thread = None
        self._running = True

        self._start_tick_thread()

    # ── 播放列表 ──────────────────────────────────────────

    def add_song(self, path, title="", artists=""):
        """添加歌曲到播放列表末尾（自动去重）"""
        path = str(path)
        if not os.path.exists(path):
            return False
        with self._lock:
            # 路径去重
            for s in self.playlist:
                if s["path"] == path:
                    return False
            self.playlist.append({"path": path, "title": title, "artists": artists})
        return True

    def remove_song(self, index):
        """移除指定索引"""
        with self._lock:
            if 0 <= index < len(self.playlist):
                was_current = (index == self.current_index)
                self.playlist.pop(index)
                if was_current:
                    self.stop()
                elif index < self.current_index:
                    self.current_index -= 1
                return True
        return False

    def clear_playlist(self):
        """清空列表并停止"""
        with self._lock:
            self.stop()
            self.playlist.clear()
            self.current_index = -1

    def get_playlist(self):
        """返回列表副本"""
        with self._lock:
            return list(self.playlist)

    # ── 播放控制 ──────────────────────────────────────────

    def play_index(self, index):
        """播放指定索引"""
        with self._lock:
            if not (0 <= index < len(self.playlist)):
                return False
            self.current_index = index
            path = self.playlist[index]["path"]

        try:
            # 按源流采样率重配 mixer，48k 源不再被压到 44.1k 重采样
            freq, ch = _probe_stream_info(path)
            if freq:
                _ensure_mixer(freq, ch)
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(self.volume)
            pygame.mixer.music.play()
            self._paused = False
            self._stopped = False
            self._song_ended = False
            # 切歌时缓存时长，避免后续每次 tick 都重建 Sound 对象
            self._cached_duration = self._compute_duration(path)
            # 新歌从头播放，重置 seek 偏移基准
            self._seek_base = 0.0
            self._seek_clock = 0.0
            return True
        except Exception as e:
            print(f"[Player] 加载失败: {path} — {e}")
            return False

    def play_pause(self):
        """切换播放/暂停"""
        if self._stopped:
            # 从未播放过，从头开始
            if self.playlist:
                return self.play_index(0)
            return False

        if self._paused:
            pygame.mixer.music.unpause()
            self._paused = False
        else:
            pygame.mixer.music.pause()
            self._paused = True
        return True

    def stop(self):
        """停止"""
        pygame.mixer.music.stop()
        self._stopped = True
        self._paused = False

    def next(self):
        """下一首"""
        if not self.playlist:
            return False
        with self._lock:
            n = len(self.playlist)
            if self.mode == MODE_RANDOM:
                idx = random.randrange(n)
            elif self.mode == MODE_REPEAT:
                idx = self.current_index
            else:
                idx = (self.current_index + 1) % n
        return self.play_index(idx)

    def prev(self):
        """上一首"""
        if not self.playlist:
            return False
        with self._lock:
            n = len(self.playlist)
            if self.mode == MODE_RANDOM:
                idx = random.randrange(n)
            elif self.mode == MODE_REPEAT:
                idx = self.current_index
            else:
                idx = (self.current_index - 1 + n) % n
        return self.play_index(idx)

    # ── 进度 ──────────────────────────────────────────────

    def get_position(self):
        """返回当前播放位置(秒)，未播放返回0（含 seek 偏移修正）"""
        if self._stopped:
            return 0
        raw = pygame.mixer.music.get_pos()
        if raw < 0:
            return self._seek_base
        # get_pos() 从 play() 起累计且不含 set_pos() 偏移：
        # 真实位置 = seek 基准 + (当前读数 - seek 时读数)
        return max(0.0, self._seek_base + (raw / 1000.0 - self._seek_clock))

    def seek(self, pos_sec):
        """跳转到指定秒数（需要 pygame 2.x + 支持的格式如 mp3/ogg）"""
        if self._stopped:
            return False
        try:
            pygame.mixer.music.set_pos(pos_sec)
            # 记录偏移基准，供 get_position() 换算
            raw = pygame.mixer.music.get_pos()
            if raw >= 0:
                self._seek_clock = raw / 1000.0
            self._seek_base = float(pos_sec)
            self._song_ended = False
            return True
        except Exception:
            # 某些格式不支持 seek（如部分 m4a/opus）
            return False

    # ── 音量 ──────────────────────────────────────────────

    def set_volume(self, vol):
        """vol: 0.0 ~ 1.0"""
        self.volume = max(0.0, min(1.0, vol))
        pygame.mixer.music.set_volume(self.volume)

    # ── 播放模式 ──────────────────────────────────────────

    def set_mode(self, mode):
        """MODE_ORDER / MODE_RANDOM / MODE_REPEAT"""
        self.mode = mode

    # ── 状态查询 ──────────────────────────────────────────

    def is_playing(self):
        return not self._stopped and not self._paused and pygame.mixer.music.get_busy()

    def is_paused(self):
        return self._paused

    def current_song(self):
        """返回当前歌曲信息 dict 或 None"""
        with self._lock:
            if 0 <= self.current_index < len(self.playlist):
                return dict(self.playlist[self.current_index])
        return None

    # ── 内部 ──────────────────────────────────────────────

    def _start_tick_thread(self):
        def tick_loop():
            while self._running:
                time.sleep(0.5)
                if self._stopped or self._paused:
                    continue
                try:
                    busy = pygame.mixer.music.get_busy()
                except pygame.error:
                    # mixer 正被重配或已关闭（切歌/退出窗口期）— 本轮跳过
                    continue
                if not busy:
                    # 歌曲自然结束 — 只触发一次
                    if not self._song_ended and not self._paused and not self._stopped:
                        self._song_ended = True
                        if self.on_song_end:
                            self.on_song_end()
                    continue
                self._song_ended = False
                if self.on_tick:
                    pos = self.get_position()
                    total = self.get_duration()
                    self.on_tick(pos, total)

        self._tick_thread = threading.Thread(target=tick_loop, daemon=True)
        self._tick_thread.start()

    def get_duration(self):
        """获取当前歌曲总时长(秒)，不可用时返回 0（使用缓存，切歌时自动更新）"""
        return self._cached_duration

    def _compute_duration(self, path):
        """仅在切歌时调用：优先轻量读取时长（毫秒级），
        不可用时回退 pygame Sound 全量解码（FLAC/WAV 大文件可达数秒）"""
        # 1) mutagen（若已安装）：元数据读时长，全格式毫秒级
        try:
            from mutagen import File as MutagenFile
            mfile = MutagenFile(path)
            if mfile is not None and mfile.info is not None:
                length = getattr(mfile.info, "length", 0)
                if length:
                    return float(length)
        except Exception:
            pass
        # 2) WAV：标准库直接读头，不解码
        if str(path).lower().endswith(".wav"):
            try:
                import wave
                with wave.open(str(path), "rb") as w:
                    if w.getframerate():
                        return w.getnframes() / w.getframerate()
            except Exception:
                pass
        # 3) 回退：pygame 全量解码（MP3 尚可，无损大文件较慢）
        try:
            sound = pygame.mixer.Sound(path)
            return sound.get_length()
        except Exception:
            return 0

    def shutdown(self):
        """关闭引擎"""
        self._running = False
        self.stop()
        pygame.mixer.quit()


# ══════════════════════════════════════════════════════════
#  辅助: 扫描目录内所有音频文件
# ══════════════════════════════════════════════════════════

AUDIO_EXTS = {".mp3", ".m4a", ".opus", ".flac", ".wav", ".ogg", ".aac", ".wma"}


def scan_audio_files(directory):
    """扫描目录返回 [{path, title, artists}]"""
    directory = Path(directory)
    if not directory.exists():
        return []
    songs = []
    for p in sorted(directory.iterdir()):
        if p.suffix.lower() in AUDIO_EXTS:
            # 尝试从文件名解析 title — artists
            stem = p.stem
            parts = stem.split(" — ", 1)
            if len(parts) == 2:
                title, artists = parts
            else:
                title = stem
                artists = ""
            songs.append({"path": str(p), "title": title, "artists": artists})
    return songs
