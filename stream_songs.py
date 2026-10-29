#!/usr/bin/env python3
"""在线曲库内置精选歌单。

开箱即有内容: 这些歌曲已通过网易云 outer/url 直链验证(见探测记录),
多为免费可整首播的版本, 光辉岁月为 VIP 30s 试听。id 固定,
不依赖实时搜索接口, 进 tab 即有列表; 点歌时才联网拉流。

字段与 mget.netease_search 的返回保持一致, 直接喂给在线曲库表格与
播放/下载管线 (preview_url / download_url / search_query / id / fee)。
"""

_BASE = "https://music.163.com/song/media/outer/url?id={id}.mp3"


def _song(name, artists, sid, dur, fee=0, album=""):
    url = _BASE.format(id=sid)
    return {
        "name": name,
        "artists": artists,
        "album": album,
        "duration": dur,
        "id": sid,
        "fee": fee,
        "search_query": f"{name} {artists}",
        "preview_url": url,
        "download_url": url,
    }


CURATED = [
    _song("起风了", "小7", 2143071143, 326.0),
    _song("酒窝", "刘光蕊", 521956771, 263.0),
    _song("老男孩", "ORCA特米", 2688454170, 296.0),
    _song("南山南", "小管", 1993677665, 247.0),
    _song("青花瓷", "刘芳", 259138, 268.0),
    _song("东风破", "长风遇聪", 3417814990, 325.0),
    _song("夜曲", "武钟旭", 2635327867, 225.0),
    _song("简单爱", "王大毛", 2704580645, 270.0),
    _song("七里香", "王俊凯", 2108553289, 301.0),
    _song("后来", "刘若英", 34834580, 341.0),
    _song("小芳", "刘铁钢", 3322457706, 198.0),
    _song("爱在深秋", "nengcd", 1979964354, 125.0),
    _song("可惜没如果", "Masque", 1327832068, 283.0),
    _song("光辉岁月", "Beyond", 346576, 298.0, fee=1),
]


def get_curated(limit=None):
    """返回内置精选歌单 (完整 dict 列表), 可选截断前 limit 首。"""
    return CURATED if limit is None else CURATED[:limit]
