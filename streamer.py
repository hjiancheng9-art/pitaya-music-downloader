#!/usr/bin/env python3
"""
StreamerEngine — VLC 流式播放引擎
基于 python-vlc，支持 URL 直播，无需下载
API 兼容 PlayerEngine 的核心操作
"""

import threading
import time

import vlc


class StreamerEngine:
    """VLC-based streaming engine. Thread-safe. Mirrors PlayerEngine API."""

    def __init__(self, on_tick=None, on_song_end=None, on_error=None):
        """
        on_tick:      callable(cur_pos_sec, total_sec) — 每 0.5s 回调进度
        on_song_end:  callable() — 歌曲自然结束回调
        on_error:     callable(msg) — 播放出错回调
        """
        self._url = None
        self._title = ""
        self._artists = ""
        self._volume = 0.8
        self._paused = False
        self._stopped = True
        self._song_ended = False
        self._running = True

        self.on_tick = on_tick
        self.on_song_end = on_song_end
        self.on_error = on_error

        self._lock = threading.Lock()
        self._tick_thread = None

        # 创建 VLC 实例（无 GUI 模式）
        self._instance = vlc.Instance("--quiet")
        self._player = self._instance.media_player_new()
        self._player.audio_set_volume(int(self._volume * 100))

        self._start_tick_thread()

    # ── 播放控制 ──────────────────────────────────────────

    def play_url(self, url, title="", artists=""):
        """播放 URL 流，自动停掉当前播放"""
        with self._lock:
            if not self._stopped:
                self._player.stop()

            self._url = url
            self._title = title
            self._artists = artists
            self._paused = False
            self._stopped = False
            self._song_ended = False

            media = self._instance.media_new(url)
            self._player.set_media(media)
            ret = self._player.play()
            media.release()

            if ret == -1:
                self._stopped = True
                return False
        return True

    def play_pause(self):
        """切换 暂停 / 继续"""
        if self._stopped:
            return False
        if self._paused:
            self._player.play()
            self._paused = False
        else:
            self._player.pause()
            self._paused = True
        return True

    def stop(self):
        """停止播放"""
        with self._lock:
            self._player.stop()
            self._stopped = True
            self._paused = False
            self._song_ended = False

    # ── 音量 ──────────────────────────────────────────────

    def set_volume(self, vol):
        """vol: 0.0 ~ 1.0"""
        self._volume = max(0.0, min(1.0, vol))
        self._player.audio_set_volume(int(self._volume * 100))

    # ── 进度 ──────────────────────────────────────────────

    def get_position(self):
        """当前播放位置（秒）"""
        if self._stopped:
            return 0
        ms = self._player.get_time()
        return ms / 1000.0 if ms > 0 else 0

    def get_duration(self):
        """总时长（秒），流媒体可能返回 0"""
        ms = self._player.get_length()
        return ms / 1000.0 if ms > 0 else 0

    def seek(self, pos_sec):
        """跳转到指定秒数"""
        if self._stopped:
            return False
        try:
            self._player.set_time(int(pos_sec * 1000))
            self._song_ended = False
            return True
        except Exception:
            return False

    # ── 状态查询 ──────────────────────────────────────────

    def is_playing(self):
        return not self._stopped and not self._paused

    def is_paused(self):
        return self._paused

    def is_stopped(self):
        return self._stopped

    def current_song(self):
        """返回当前歌曲信息 dict 或 None"""
        if self._stopped:
            return None
        return {"url": self._url, "title": self._title, "artists": self._artists}

    # ── 内部 ──────────────────────────────────────────────

    def _start_tick_thread(self):
        def tick_loop():
            while self._running:
                time.sleep(0.5)

                with self._lock:
                    if self._stopped or self._paused:
                        continue

                    state = self._player.get_state()

                    if state == vlc.State.Error:
                        self._stopped = True
                        self._paused = False
                        if self.on_error:
                            self.on_error("播放失败，链接可能已失效或网络不通")
                        continue

                    if state == vlc.State.Ended:
                        if not self._song_ended:
                            self._song_ended = True
                            self._stopped = True
                            self._paused = False
                            if self.on_song_end:
                                self.on_song_end()
                        continue

                    if state == vlc.State.Playing:
                        self._song_ended = False
                        if self.on_tick:
                            pos = self.get_position()
                            total = self.get_duration()
                            self.on_tick(pos, total)

        self._tick_thread = threading.Thread(target=tick_loop, daemon=True)
        self._tick_thread.start()

    def shutdown(self):
        """释放 VLC 资源"""
        self._running = False
        with self._lock:
            self._player.stop()
        self._player.release()
        self._instance.release()


# ══════════════════════════════════════════════════════════
#  自测
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    ended = threading.Event()

    def on_tick(pos, total):
        print(f"  ▶ {pos:.1f}s / {total:.1f}s", end="\r")

    def on_end():
        print("\n  播放结束")
        ended.set()

    def on_err(msg):
        print(f"\n  错误: {msg}")
        ended.set()

    se = StreamerEngine(on_tick=on_tick, on_song_end=on_end, on_error=on_err)

    test_url = "https://music.163.com/song/media/outer/url?id=186001.mp3"
    print(f"测试 URL: {test_url}")
    ok = se.play_url(test_url, title="晴天", artists="周杰伦")

    if not ok:
        print("播放启动失败")
        se.shutdown()
        sys.exit(1)

    print("播放中，按 Enter 停止...")
    try:
        ended.wait(timeout=30)
    except KeyboardInterrupt:
        pass

    se.shutdown()
    print("完毕")
