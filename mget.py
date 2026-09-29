#!/usr/bin/env python3
"""
mget — 极简音乐下载器
功能：搜索 → 选择 → 下载
音源：网易云直链（免费）/ YouTube / SoundCloud / Bilibili
策略：网易云直链优先 → 多音源自动回退 → 按源控制代理 → 多浏览器 Cookies → 多客户端伪装
"""

import sys
import os
import re
import time
import webbrowser
import yaml
import yt_dlp
import urllib.error
import urllib.request
from pathlib import Path

import requests

# 自动代理检测
from proxy_detector import find_best_proxy


# ════════════════════════════════════════════════════════════
#  源配置与常量
# ════════════════════════════════════════════════════════════

SOURCES = {
    "youtube": {
        "name": "YouTube",
        "search_prefix": "ytsearch",
        "needs_proxy": True,
        "extract_flat": True,
        "url_builder": lambda vid: f"https://www.youtube.com/watch?v={vid}",
    },
    "soundcloud": {
        "name": "SoundCloud",
        "search_prefix": "scsearch",
        "needs_proxy": True,
        "extract_flat": True,
        "url_builder": None,  # extract_flat 自带完整 URL
    },
    "bilibili": {
        "name": "Bilibili",
        "search_prefix": "bilisearch",
        "needs_proxy": False,  # 国内直连，走代理反而被墙
        "extract_flat": True,
        "url_builder": lambda vid: (
            f"https://www.bilibili.com/video/{vid}"
            if str(vid).startswith("BV")
            else f"https://www.bilibili.com/video/av{vid}"
        ),
        # Bilibili 单独下载，不需要反bot策略
        "download_handler": "direct",
    },
}

# HTTP 伪装头
FAKE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}

# 多浏览器 cookies 回退（仅 YouTube 类反 bot 源使用）
BROWSER_FALLBACK = ["chrome", "edge", "firefox", "opera", "brave"]

# YouTube 多客户端策略
YT_STRATEGIES = [
    {"youtube": {"player_client": ["web"]}},
    {"youtube": {"player_client": ["android"]}},
    {"youtube": {"player_client": ["ios"]}},
    {"youtube": {"player_client": ["web_embedded"]}},
    {"youtube": {"player_skip": ["webpage", "configs"]}},
    {},
]


# ════════════════════════════════════════════════════════════
#  错误信息汉化
# ════════════════════════════════════════════════════════════

def translate_error(err):
    msg = str(err).lower()

    if "http error 403" in msg or "forbidden" in msg:
        return "服务器拒绝连接（HTTP 403）。可能是被墙、需要代理或换音源。"
    if "http error 404" in msg:
        return "页面不存在（HTTP 404），可能已删除或链接失效。"
    if "http error 429" in msg:
        return "请求过于频繁（HTTP 429），请稍等几分钟再试。"
    if "http error" in msg:
        m = re.search(r"http error (\d+)", msg)
        return f"网络请求失败（HTTP {m.group(1) if m else '未知'}）。"
    if "unable to download api page" in msg:
        return "无法访问搜索接口。请检查网络连接。"
    if "connection" in msg or "refused" in msg or "reset" in msg:
        return "网络连接失败。请检查网络设置。"
    if "ssl" in msg or "certificate" in msg:
        return "SSL 证书验证失败。可能是代理或网络环境导致。"
    if "timeout" in msg or "timed out" in msg:
        return "请求超时。网络不稳定或连接被阻断。"
    if "no such file" in msg:
        return "文件不存在。可能是下载路径配置有误。"
    if "ffmpeg" in msg:
        return "FFmpeg 处理失败。请确认已安装 FFmpeg 并添加到系统 PATH。"
    if "not available in your country" in msg:
        return "该视频在你所在地区不可用（地区限制）。"
    if "private video" in msg or "sign in" in msg:
        return "该视频为私有或需要登录，无法下载。"
    if "age restricted" in msg:
        return "该视频有年龄限制，无法下载。"
    if "player response" in msg:
        return "YouTube 反爬拦截。已尝试所有策略。"
    if "412" in msg:
        return "Bilibili 反爬拦截（HTTP 412）。请稍后再试。"

    return f"下载出错: {str(err)[:120]}"


# ════════════════════════════════════════════════════════════
#  配置加载
# ════════════════════════════════════════════════════════════

def load_config():
    cfg_path = Path(__file__).parent / "config.yaml"
    if not cfg_path.exists():
        print("[配置] 未找到 config.yaml，使用默认配置")
        default = {
            "output_dir": "~/Music/mget",
            "audio_format": "mp3",
            "audio_quality": 0,
            "embed_metadata": True,
            "embed_thumbnail": True,
            "search_count": 20,
            "source_priority": ["youtube", "soundcloud", "bilibili"],
            "netease_direct": True,
            "proxy": None,
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(default, f, allow_unicode=True, default_flow_style=False)
        # 不再 sys.exit — 让调用方（包括 GUI）可以继续使用默认配置
        cfg = dict(default)
        cfg["output_dir"] = os.path.expanduser(cfg["output_dir"])
        os.makedirs(cfg["output_dir"], exist_ok=True)
        return cfg

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # 兼容旧配置
    if "source" in cfg and "source_priority" not in cfg:
        cfg["source_priority"] = [cfg["source"], "bilibili"]

    cfg["output_dir"] = os.path.expanduser(cfg["output_dir"])
    os.makedirs(cfg["output_dir"], exist_ok=True)

    # 自动代理检测 + 有效性验证
    if not cfg.get("proxy"):
        detected = find_best_proxy()
        if detected:
            proxy_url = detected["url"]
            if _validate_proxy(proxy_url):
                cfg["proxy"] = proxy_url
                print(f"[代理] 已启用: {detected['name']} ({proxy_url})")
            else:
                cfg["proxy"] = None
                print(f"[代理] {detected['name']} 端口开放但代理不可用，已忽略")
        else:
            cfg["proxy"] = None
    else:
        # 用户手动设置的代理也验证一下
        if not _validate_proxy(cfg["proxy"]):
            print(f"[代理] 手动设置的代理 {cfg['proxy']} 不可用")
            cfg["proxy"] = None

    return cfg


def _validate_proxy(proxy_url, timeout=5):
    """验证代理是否真实可用，测试访问 Google"""
    try:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request("http://www.google.com", headers={
            "User-Agent": "Mozilla/5.0"
        })
        resp = opener.open(req, timeout=timeout)
        return resp.status in (200, 301, 302)
    except Exception:
        return False


# ════════════════════════════════════════════════════════════
#  搜索引擎
# ════════════════════════════════════════════════════════════

def _get_ydl_opts(cfg, source_key, is_download=False):
    """构建 yt-dlp 选项，根据音源控制是否走代理"""
    source = SOURCES[source_key]
    opts = {
        "quiet": True,
        "no_warnings": True,
        "force_generic_extractor": False,
        "http_headers": FAKE_HEADERS,
    }
    # 关键：只有需要代理的源才传 proxy
    if source.get("needs_proxy") and cfg.get("proxy"):
        opts["proxy"] = cfg["proxy"]
    if source.get("extract_flat"):
        opts["extract_flat"] = True
    return opts


def _search_source(keyword, cfg, source_key):
    """在指定源搜索，返回 (results: list, ok: bool)"""
    source = SOURCES[source_key]
    query = f"{source['search_prefix']}{cfg['search_count']}:{keyword}"
    opts = _get_ydl_opts(cfg, source_key)

    # Bilibili 容易 412，多试几次
    max_retries = 3 if source_key == "bilibili" else 1
    last_error = None

    for attempt in range(max_retries):
        if attempt > 0:
            time.sleep(2 * attempt)

        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "412" in err_str and attempt < max_retries - 1:
                    continue
                print(f"    {source['name']}: {translate_error(e)}")
                return [], False

        entries = info.get("entries", [])
        if not entries:
            print(f"    {source['name']}: 未找到结果")
            return [], False

        results = []
        need_title = []  # (results 下标, url) — bilibili 缺标题的条目，稍后并行补抓
        for e in entries:
            if not e:
                continue
            vid = e.get("id", "")
            url = e.get("url") or e.get("webpage_url") or e.get("original_url") or ""

            # URL 构建回退
            if not url and vid and source.get("url_builder"):
                url = source["url_builder"](vid)

            if not url:
                continue

            title = e.get("title")
            duration = e.get("duration") or 0

            if not title and source_key == "bilibili":
                need_title.append((len(results), url))

            results.append({
                "title": title,
                "duration": duration,
                "url": url,
                "id": vid,
                "source": source_key,
            })

        # 并行补抓缺失标题：串行逐条抓 20 条可能阻塞近 1 分钟，4 并发降到约 1/4
        if need_title:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=4) as pool:
                fetched = pool.map(
                    lambda u: _fetch_bili_title(u, cfg),
                    [u for _, u in need_title])
                for (idx, _), title in zip(need_title, fetched):
                    if title:
                        results[idx]["title"] = title

        # 仍缺标题的条目用占位符兜底
        for r in results:
            if not r["title"]:
                vid = r["id"]
                r["title"] = f"[{source['name']}] {vid[:10]}" if vid else f"[{source['name']}] 未知视频"

        return results, True

    print(f"    {source['name']}: {translate_error(last_error)}")
    return [], False


def _fetch_bili_title(url, cfg):
    """单独获取 Bilibili 视频标题"""
    try:
        opts = _get_ydl_opts(cfg, "bilibili")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get("title")
    except Exception:
        return None


def search_multi(keyword, cfg):
    """按配置优先级在多个源搜索，自动回退。
    多源并行搜索（每个线程独立 yt-dlp 实例，线程安全），结果仍按优先级聚合"""
    priority = cfg.get("source_priority", ["youtube", "bilibili"])
    valid = []
    for src in priority:
        if src in SOURCES:
            valid.append(src)
        else:
            print(f"    未知音源: {src}，跳过")

    if not valid:
        return []

    tags = ", ".join(
        "%s[%s]" % (
            SOURCES[s]["name"],
            "代理" if (SOURCES[s].get("needs_proxy") and cfg.get("proxy")) else "直连",
        )
        for s in valid
    )
    print(f"  并行搜索: {tags} ...")

    # 并行搜索所有源：总耗时 = 最慢的源，而不是所有源之和
    if len(valid) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(valid)) as pool:
            futures = {src: pool.submit(_search_source, keyword, cfg, src)
                       for src in valid}
            results_by_src = {src: futures[src].result() for src in valid}
    else:
        results_by_src = {valid[0]: _search_source(keyword, cfg, valid[0])}

    all_results = []
    sources_ok = []
    sources_failed = []
    for src in valid:
        results, ok = results_by_src[src]
        if ok and results:
            sources_ok.append(src)
            all_results.extend(results)
            print(f"    {SOURCES[src]['name']}: 找到 {len(results)} 首")
        else:
            sources_failed.append(src)
            print(f"    {SOURCES[src]['name']}: 失败，跳过")

    if not all_results:
        print("\n  所有音源均未找到结果。")
        if sources_failed:
            print("  提示: 检查代理是否正常（需要翻墙的源），或 Bilibili 直连是否正常。")
        return []

    print(f"\n  共找到 {len(all_results)} 首（来源: {', '.join(sources_ok)}）")
    return all_results


# ════════════════════════════════════════════════════════════
#  网易云搜索 — 拿精确歌名/歌手，再交给 yt-dlp 下载
# ════════════════════════════════════════════════════════════

def netease_search(keyword, limit=20):
    """搜索网易云音乐，返回结构化结果（歌名、歌手、专辑、时长）"""
    try:
        resp = requests.get(
            "http://music.163.com/api/search/get",
            params={"s": keyword, "type": 1, "limit": limit, "offset": 0},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Referer": "https://music.163.com/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            },
            timeout=15,
        )
        data = resp.json()
        if data.get("code") != 200:
            return []

        songs = data.get("result", {}).get("songs", [])
        results = []
        for s in songs:
            name = s.get("name", "")
            artists = " / ".join(a.get("name", "") for a in s.get("artists", []))
            album = s.get("album", {}).get("name", "") if s.get("album") else ""
            duration = (s.get("duration") or 0) / 1000
            sid = s.get("id")
            fee = s.get("fee", 0)  # 0=免费, 1=VIP 付费
            # 构造精确搜索词，提高命中率
            search_query = f"{name} {artists}" if artists else name
            results.append({
                "name": name,
                "artists": artists,
                "album": album,
                "duration": duration,
                "id": sid,
                "fee": fee,
                "search_query": search_query,
                "preview_url": f"https://music.163.com/song/media/outer/url?id={sid}.mp3",
                "download_url": f"https://music.163.com/song/media/outer/url?id={sid}.mp3",
            })
        return results
    except Exception as e:
        print(f"  网易云搜索失败: {e}")
        return []


def display_netease_results(results, keyword):
    print(f"\n  搜索: {keyword}")
    print("-" * 55)
    for i, r in enumerate(results, 1):
        dur = fmt_duration(r["duration"])
        name = r["name"] if len(r["name"]) <= 30 else r["name"][:28] + ".."
        artists = r["artists"] if len(r["artists"]) <= 20 else r["artists"][:18] + ".."
        album = f" · {r['album']}" if r["album"] else ""
        # fee != 0 matches the direct-download gate in download_netease
        vip = " 【VIP】" if r.get("fee", 0) else ""
        print(f"  [{i:2d}] {name}{vip}  — {artists}{album}  ({dur})")
    print("-" * 55)
    print("  输入数字选择 | p <编号> 试听 | all 全选 | q 退出")


def preview_song(song):
    """用系统默认浏览器打开网易云试听链接"""
    url = song["preview_url"]
    name = song["name"]
    artists = song["artists"]
    print(f"  试听: {name} — {artists}")
    print(f"  {url}")
    webbrowser.open(url)


def parse_multi_select(raw, max_idx):
    """解析用户输入，支持 '1,3,5', '1-5', 'all', 返回去重排序后的序号列表"""
    raw = raw.strip()

    if raw.lower() == "all":
        return list(range(max_idx))

    if raw.lower() == "q":
        return None

    indexes = set()
    for part in raw.replace("，", ",").split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                indexes.update(range(int(a) - 1, int(b)))
            except (ValueError, TypeError):
                continue
        else:
            try:
                idx = int(part) - 1
                if 0 <= idx < max_idx:
                    indexes.add(idx)
            except ValueError:
                continue

    if not indexes:
        return None

    return sorted(indexes)


# ════════════════════════════════════════════════════════════
#  下载引擎
# ════════════════════════════════════════════════════════════

def _build_dl_opts(cfg, source_key, cookies_browser=None, extractor_args=None):
    """构建下载用 yt-dlp 选项"""
    source = SOURCES[source_key]
    out_tmpl = os.path.join(cfg["output_dir"], "%(title)s.%(ext)s")
    # audio_format = "best" 时不转码：保留 yt-dlp 抓到的原始流
    # （opus/m4a 原样落盘），避免一次有损的 MP3 代际转码
    postprocessors = []
    if cfg["audio_format"] != "best":
        postprocessors.append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": cfg["audio_format"],
                "preferredquality": str(cfg["audio_quality"]),
            }
        )
    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_tmpl,
        "quiet": False,
        "no_warnings": True,
        "http_headers": FAKE_HEADERS,
        "postprocessors": postprocessors,
        "postprocessor_args": {"ffmpeg": ["-y"]},
    }
    # 按源控制代理
    if source.get("needs_proxy") and cfg.get("proxy"):
        opts["proxy"] = cfg["proxy"]
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if extractor_args:
        opts["extractor_args"] = extractor_args
    if cfg.get("embed_metadata"):
        opts["postprocessors"].append({"key": "FFmpegMetadata"})
    if cfg.get("embed_thumbnail"):
        opts["writethumbnail"] = True
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
    return opts


def _fmt_speed(speed):
    """速度格式化：B/s / KB/s / MB/s"""
    if speed > 1024 * 1024:
        return f"{speed / 1024 / 1024:.1f} MB/s"
    elif speed > 1024:
        return f"{speed / 1024:.0f} KB/s"
    return f"{speed:.0f} B/s"


def download_netease(song, cfg, progress_callback=None):
    """网易云直链下载：免费歌曲通过 outer/url 接口直接下载 mp3。

    参数:
        song: netease_search 返回的 dict（含 id、fee、name、artists）
        cfg: 配置 dict（用 output_dir）
        progress_callback(pct, speed_str): 可选，下载中回调。
            pct 为 -1 时表示无法确定总大小（speed_str 仍有效）。
    返回:
        (ok: bool, error_msg: str)
    """
    name = song.get("name", "")
    artists = song.get("artists", "")
    sid = song.get("id")

    if not sid:
        return False, "缺少歌曲 ID"
    if song.get("fee", 0) != 0:
        return False, "VIP 付费歌曲，平台限制无法直接下载"

    url = song.get("download_url") or (
        f"https://music.163.com/song/media/outer/url?id={sid}.mp3")

    headers = {
        "User-Agent": FAKE_HEADERS["User-Agent"],
        "Referer": "https://music.163.com/",
        "Accept": "*/*",
    }

    try:
        resp = requests.get(url, headers=headers, stream=True,
                            timeout=30, allow_redirects=True)
    except Exception as e:
        return False, f"请求失败: {e}"

    if resp.status_code == 403:
        return False, "版权受限，链接被拦截（HTTP 403）"
    if resp.status_code != 200:
        return False, f"下载失败（HTTP {resp.status_code}）"

    # 返回 HTML 错误页（而非音频）视为无效链接
    ct = resp.headers.get("content-type", "")
    if "text/html" in ct.lower():
        return False, "链接无效（可能为 VIP 或版权受限）"

    # 清理文件名非法字符
    filename = f"{name}-{artists}".strip("-") + ".mp3"
    for ch in r'<>:"/\|?*':
        filename = filename.replace(ch, "_")
    filepath = os.path.join(cfg["output_dir"], filename)

    total = int(resp.headers.get("content-length", 0) or 0)
    downloaded = 0
    start = time.time()
    last_t = start
    last_d = 0
    speed_str = ""

    try:
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                dt = now - last_t
                if dt >= 0.3:
                    speed_str = _fmt_speed((downloaded - last_d) / dt)
                    last_t = now
                    last_d = downloaded
                pct = int(downloaded / total * 100) if total > 0 else -1
                if progress_callback:
                    progress_callback(pct, speed_str)
                elif total > 0:
                    print(f"\r  下载进度: {pct}%", end="")
    except Exception as e:
        return False, f"下载失败: {e}"

    # 完整性校验
    if downloaded == 0:
        return False, "下载内容为空"
    if total > 0 and downloaded < total:
        return False, "下载不完整，请重试"

    if progress_callback is None and total > 0:
        print()
    print(f"  完成!  {filepath}")
    return True, ""


def download_direct(result, cfg):
    """直接下载：Bilibili / SoundCloud 等不需要反bot策略的源"""
    src = result.get("source", "bilibili")
    opts = _build_dl_opts(cfg, src)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([result["url"]])
        print(f"  完成!  {cfg['output_dir']}")
        return True
    except Exception as e:
        print(f"  {translate_error(e)}")
        return False


def download_anti_bot(result, cfg):
    """YouTube 反 bot 下载：多策略重试"""
    tried = []
    for browser in BROWSER_FALLBACK:
        for strat in YT_STRATEGIES:
            label = f"{browser}+{_yt_label(strat)}"
            if label in tried:
                continue
            tried.append(label)

            opts = _build_dl_opts(cfg, "youtube", browser, strat)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([result["url"]])
                print(f"  完成!  {cfg['output_dir']}")
                return True
            except yt_dlp.utils.DownloadError as e:
                err = str(e).lower()
                if "player response" in err or "bot" in err:
                    print(f"  [{label}] 被拦截，切换策略...")
                else:
                    print(f"  [{label}] {translate_error(e)}")
                    if "404" in err or "private" in err or "not available" in err:
                        return False
            except Exception as e:
                print(f"  [{label}] {translate_error(e)}")

    return False


def download(result, cfg, tried_sources=None):
    """下载一首歌，失败自动回退其他音源"""
    if tried_sources is None:
        tried_sources = set()

    src = result.get("source", "youtube")
    if src in tried_sources:
        return False

    source = SOURCES.get(src, {})
    print(f"\n  {source.get('name', src)}: {result['title']}")
    print(f"  保存到: {cfg['output_dir']}")

    # 判断走反bot还是直接下载
    if src in ("youtube",):
        ok = download_anti_bot(result, cfg)
    else:
        ok = download_direct(result, cfg)

    tried_sources.add(src)

    if ok:
        return True

    # 下载失败，尝试回退到其他音源
    priority = cfg.get("source_priority", [])
    for fallback_src in priority:
        if fallback_src in tried_sources:
            continue

        fallback = SOURCES.get(fallback_src, {})
        print(f"\n    {source.get('name', src)} 失败，尝试 {fallback.get('name', fallback_src)}...")
        results2, _ = _search_source(result["title"], cfg, fallback_src)
        if results2:
            ok = download(results2[0], cfg, tried_sources)
            if ok:
                return True

    print(f"\n    所有音源均失败")
    return False


def _yt_label(strat):
    if not strat:
        return "默认"
    for v in strat.values():
        if "player_client" in v:
            return v["player_client"][0] if v.get("player_client") else "?"
        if "player_skip" in v:
            return "skip"
    return "自定义"


# ════════════════════════════════════════════════════════════
#  格式化 & 展示
# ════════════════════════════════════════════════════════════

def fmt_duration(sec):
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def display_results(results, keyword):
    print(f"\n  搜索: {keyword}")
    print("-" * 50)

    current_source = None
    for i, r in enumerate(results, 1):
        if r["source"] != current_source:
            current_source = r["source"]
            src_name = SOURCES.get(current_source, {}).get("name", current_source)
            print(f"\n    [{src_name}]")
        dur = fmt_duration(r["duration"])
        title = r["title"] if len(r["title"]) <= 60 else r["title"][:57] + "..."
        print(f"  [{i:2d}] {title}  ({dur})")
    print("-" * 50)


# ════════════════════════════════════════════════════════════
#  主流程
# ════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python mget.py <歌名> [歌手]")
        print("示例: python mget.py 海阔天空 Beyond")
        print("      python mget.py 七里香 周杰伦")
        print()
        print("来源: 网易云音乐（搜歌名） → YouTube/SoundCloud/Bilibili（下载）")
        sys.exit(1)

    keyword = " ".join(sys.argv[1:])

    # ── 第一步: 网易云搜歌 ──
    print(f"搜索网易云: {keyword}")
    net_results = netease_search(keyword)

    if not net_results:
        print("  无结果，切换到直接搜索模式...")
        _legacy_flow(keyword)
        return

    display_netease_results(net_results, keyword)

    # ── 第二步: 多选 ──
    while True:
        raw = input(
            f"\n选择 (1-{len(net_results)}), 支持 1,3,5 或 1-5 或 all, q 退出: "
        ).strip()
        if raw.lower() == "q":
            print("  再见!")
            sys.exit(0)

        # 试听命令: p 3 或 p 1,5
        if raw.lower().startswith("p "):
            preview_raw = raw[2:].strip()
            preview_idxs = parse_multi_select(preview_raw, len(net_results))
            if preview_idxs:
                for idx in preview_idxs:
                    preview_song(net_results[idx])
            else:
                print(f"  格式不对，试听请用 p <编号>，如 p 3")
            continue

        selections = parse_multi_select(raw, len(net_results))
        if selections is not None:
            break
        print(f"  格式不对，请输入数字（如 1,3,5 或 1-5 或 all）或 p 3 试听")

    # ── 第三步: 逐首精确搜索+下载 ──
    cfg = load_config()
    print(f"\n共 {len(selections)} 首\n{'='*50}")

    for sel in selections:
        song = net_results[sel]
        query = song["search_query"]
        name = song["name"]
        artists = song["artists"]

        print(f"\n  {name}  — {artists}")

        # 优先尝试网易云直链下载（免费歌曲，无需代理）
        if cfg.get("netease_direct", True) and song.get("fee", 0) == 0:
            print("  尝试网易云直链下载...")
            ok, err = download_netease(song, cfg)
            if ok:
                continue
            print(f"  网易云直链失败（{err}），回退其他音源...")

        print("  搜索下载中...")
        results = search_multi(query, cfg)
        if not results:
            print(f"  未找到可下载资源，跳过")
            continue

        # 取最佳匹配（第一个结果）
        download(results[0], cfg)

    print(f"\n{'='*50}")
    print(f"全部完成! 保存目录: {cfg['output_dir']}")


def _legacy_flow(keyword):
    """兜底: 直接 yt-dlp 搜索（网易云挂了或没结果时用）"""
    cfg = load_config()
    results = search_multi(keyword, cfg)
    if not results:
        print("\n提示:")
        print("  1. Bilibili 国内直连，检查网络")
        print("  2. YouTube/SoundCloud 需要代理，检查代理是否正常")
        return

    display_results(results, keyword)

    while True:
        try:
            choice = input(f"\n选择 (1-{len(results)}), 或 q 退出: ").strip()
            if choice.lower() == "q":
                print("  再见!")
                sys.exit(0)
            idx = int(choice)
            if 1 <= idx <= len(results):
                break
            print(f"  请输入 1-{len(results)} 之间的数字")
        except ValueError:
            print("  请输入数字")

    download(results[idx - 1], cfg)


if __name__ == "__main__":
    main()
