"""PlayerEngine mixer sample-rate adaptation tests.

All tests mock ``pygame.mixer`` so they run without an audio device.

Regression context: the engine used to hard-code a 44.1 kHz mixer, so
48 kHz sources (Bilibili audio tracks, most M4A/AAC) were resampled by
SDL_mixer with a low-quality algorithm — dull, harsh highs.  These tests
pin the new behaviour: probe the source stream, reconfigure the mixer
only when the target differs, and fall back safely when the device
refuses the request.
"""

from __future__ import annotations

import os
import sys
import time
import wave
from unittest.mock import MagicMock, call, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import player as player_mod  # noqa: E402
from player import PlayerEngine, _ensure_mixer, _probe_stream_info  # noqa: E402


@pytest.fixture
def mixer_mock():
    """Replace pygame.mixer wholesale; no real audio device involved."""
    with patch("pygame.mixer") as mm:
        mm.get_init.return_value = (44100, -16, 2)
        # Numeric returns keep the daemon tick thread's comparisons safe.
        mm.music.get_pos.return_value = 0
        mm.music.get_busy.return_value = True
        yield mm


# --------------------------------------------------------------------------- #
# _probe_stream_info
# --------------------------------------------------------------------------- #

class TestProbeStreamInfo:
    def test_mutagen_48k_stereo(self):
        info = MagicMock(sample_rate=48000, channels=2)
        with patch("mutagen.File", return_value=MagicMock(info=info)):
            assert _probe_stream_info("song.mp3") == (48000, 2)

    def test_mutagen_mono_clamps_to_1(self):
        info = MagicMock(sample_rate=44100, channels=1)
        with patch("mutagen.File", return_value=MagicMock(info=info)):
            assert _probe_stream_info("song.mp3") == (44100, 1)

    def test_mutagen_surround_clamps_to_2(self):
        info = MagicMock(sample_rate=48000, channels=6)
        with patch("mutagen.File", return_value=MagicMock(info=info)):
            assert _probe_stream_info("song.ac3") == (48000, 2)

    def test_mutagen_no_sample_rate_falls_through(self):
        info = MagicMock(sample_rate=None, channels=2)
        with patch("mutagen.File", return_value=MagicMock(info=info)):
            assert _probe_stream_info("x.mp3") == (None, None)

    def test_wav_header(self, tmp_path):
        # mutagen would also read WAV; force it to "unknown" so the
        # stdlib wave branch is the one under test.
        p = tmp_path / "tone.wav"
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(b"\x00\x00" * 4800)  # 0.1 s of silence
        with patch("mutagen.File", return_value=None):
            assert _probe_stream_info(str(p)) == (48000, 1)

    def test_unreadable_file_returns_none(self, tmp_path):
        p = tmp_path / "junk.bin"
        p.write_bytes(b"\x00" * 64)
        with patch("mutagen.File", return_value=None):
            assert _probe_stream_info(str(p)) == (None, None)

    def test_mutagen_crash_returns_none(self):
        with patch("mutagen.File", side_effect=Exception("bad")):
            assert _probe_stream_info("x.mp3") == (None, None)


# --------------------------------------------------------------------------- #
# _ensure_mixer
# --------------------------------------------------------------------------- #

class TestEnsureMixer:
    def test_restart_on_rate_mismatch(self, mixer_mock):
        mixer_mock.get_init.return_value = (44100, -16, 2)
        _ensure_mixer(48000, 2)
        mixer_mock.quit.assert_called_once()
        mixer_mock.pre_init.assert_called_once_with(
            frequency=48000, size=-16, channels=2, buffer=4096
        )
        mixer_mock.init.assert_called_once()

    def test_no_restart_when_matched(self, mixer_mock):
        mixer_mock.get_init.return_value = (48000, -16, 2)
        _ensure_mixer(48000, 2)
        mixer_mock.quit.assert_not_called()
        mixer_mock.init.assert_not_called()

    def test_restart_on_channels_mismatch(self, mixer_mock):
        mixer_mock.get_init.return_value = (44100, -16, 2)
        _ensure_mixer(44100, 1)  # same rate, mono source → still reconfig
        mixer_mock.pre_init.assert_called_once_with(
            frequency=44100, size=-16, channels=1, buffer=4096
        )

    def test_fallback_to_44k1_on_device_error(self, mixer_mock):
        mixer_mock.get_init.return_value = (44100, -16, 2)
        # Device rejects the 48k reconfig; fallback must retry 44.1k stereo.
        mixer_mock.init.side_effect = [RuntimeError("device busy"), None]
        _ensure_mixer(48000, 2)
        assert mixer_mock.init.call_count == 2
        assert mixer_mock.pre_init.call_args_list[-1] == call(
            frequency=44100, size=-16, channels=2, buffer=4096
        )

    def test_total_failure_does_not_raise(self, mixer_mock):
        mixer_mock.get_init.return_value = (44100, -16, 2)
        mixer_mock.init.side_effect = RuntimeError("no audio device at all")
        _ensure_mixer(48000, 2)  # must swallow — playback reports its own errors


# --------------------------------------------------------------------------- #
# PlayerEngine integration
# --------------------------------------------------------------------------- #

class TestPlayerEngineMixer:
    def test_play_index_reconfigures_for_48k(self, mixer_mock, tmp_path):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"fake")
        eng = PlayerEngine()
        eng.add_song(str(f), "t", "a")
        mixer_mock.get_init.return_value = (44100, -16, 2)
        with patch.object(player_mod, "_probe_stream_info", return_value=(48000, 2)):
            assert eng.play_index(0) is True
        mixer_mock.pre_init.assert_called_with(
            frequency=48000, size=-16, channels=2, buffer=4096
        )
        mixer_mock.music.load.assert_called_once_with(str(f))

    def test_play_index_keeps_mixer_when_matched(self, mixer_mock, tmp_path):
        f = tmp_path / "song.mp3"
        f.write_bytes(b"fake")
        eng = PlayerEngine()
        eng.add_song(str(f), "t", "a")
        mixer_mock.get_init.return_value = (44100, -16, 2)
        with patch.object(player_mod, "_probe_stream_info", return_value=(44100, 2)):
            assert eng.play_index(0) is True
        mixer_mock.quit.assert_not_called()
        mixer_mock.music.load.assert_called_once()

    def test_probe_failure_still_plays(self, mixer_mock, tmp_path):
        """Unidentifiable file → mixer untouched, playback proceeds as before."""
        f = tmp_path / "song.mp3"
        f.write_bytes(b"fake")
        eng = PlayerEngine()
        eng.add_song(str(f), "t", "a")
        with patch.object(player_mod, "_probe_stream_info", return_value=(None, None)):
            assert eng.play_index(0) is True
        mixer_mock.quit.assert_not_called()
        mixer_mock.music.load.assert_called_once()


class TestStopResume:
    """stop 后续的播语义回归。

    历史 bug: stop() 后点播放走 play_pause() 的 _stopped 分支无条件
    play_index(0) — 用户停在第 5 首，再播放就跳回第 1 首。
    修复后: 续播重播当前曲 (current_index 保留上下文)，从未播过才从头。"""

    def test_resume_replays_current_song(self, mixer_mock, tmp_path):
        files = [tmp_path / f"s{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"fake")
        eng = PlayerEngine()
        for f in files:
            eng.add_song(str(f), "t", "a")
        eng.play_index(2)
        eng.stop()

        assert eng.play_pause() is True
        # 必须重播第 3 首（索引 2），而不是跳回第 1 首
        mixer_mock.music.load.assert_called_with(str(files[2]))
        assert eng.current_index == 2

    def test_never_played_starts_from_first(self, mixer_mock, tmp_path):
        f = tmp_path / "s0.mp3"
        f.write_bytes(b"fake")
        eng = PlayerEngine()
        eng.add_song(str(f), "t", "a")
        # 从未播放 → current_index == -1 → 从头
        assert eng.play_pause() is True
        assert eng.current_index == 0
        mixer_mock.music.load.assert_called_once_with(str(f))

    def test_empty_playlist_returns_false(self, mixer_mock):
        eng = PlayerEngine()
        assert eng.play_pause() is False

    def test_mode_stop_next_past_last_stops(self, mixer_mock, tmp_path):
        from player import MODE_STOP
        files = [tmp_path / f"s{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"fake")
        eng = PlayerEngine()
        for f in files:
            eng.add_song(str(f), "t", "a")
        eng.set_mode(MODE_STOP)
        eng.play_index(2)
        assert eng.next() is False
        assert eng._stopped

    def test_mode_stop_next_midlist_advances(self, mixer_mock, tmp_path):
        from player import MODE_STOP
        files = [tmp_path / f"s{i}.mp3" for i in range(3)]
        for f in files:
            f.write_bytes(b"fake")
        eng = PlayerEngine()
        for f in files:
            eng.add_song(str(f), "t", "a")
        eng.set_mode(MODE_STOP)
        eng.play_index(0)
        assert eng.next() is True
        assert eng.current_index == 1

    def test_pause_unpause_cycle_untouched(self, mixer_mock, tmp_path):
        """暂停/恢复路径不受本次改动影响。"""
        f = tmp_path / "s0.mp3"
        f.write_bytes(b"fake")
        eng = PlayerEngine()
        eng.add_song(str(f), "t", "a")
        eng.play_index(0)
        eng.play_pause()  # 暂停
        assert eng.is_paused()
        assert eng.play_pause() is True  # 恢复
        mixer_mock.music.unpause.assert_called_once()
        # 恢复后没有重新 load（不是重播）
        assert mixer_mock.music.load.call_count == 1


class TestTickThreadResilience:
    def test_survives_mixer_not_initialized(self, mixer_mock):
        """切歌窗口期 mixer 短暂未初始化 — tick 线程必须存活而非崩掉。

        Regression: _ensure_mixer 在 quit→init 之间留有窗口，tick 线程
        恰好在此调 get_busy() 会抛 pygame.error；未加守卫时整个线程死亡，
        进度回调与自动切歌随之失效。"""
        import pygame as real_pygame

        on_end = MagicMock()
        eng = PlayerEngine(on_song_end=on_end)
        eng._stopped = False
        eng._paused = False

        calls = {"n": 0}

        def busy():
            calls["n"] += 1
            if calls["n"] == 1:
                raise real_pygame.error("mixer not initialized")
            return False

        mixer_mock.music.get_busy.side_effect = busy

        # 第一次轮询(≈0.5s)命中异常被吞掉，第二次(≈1.0s)返回 False 触发 on_end
        deadline = time.time() + 3
        while on_end.call_count == 0 and time.time() < deadline:
            time.sleep(0.05)

        assert on_end.call_count == 1
        assert eng._tick_thread.is_alive()
