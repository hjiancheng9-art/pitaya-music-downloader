#!/usr/bin/env python3
"""
Pitaya Music — 火龙果音乐
深色主题 · 网易云搜索 · 多选试听 · 进度追踪
"""

import sys
import os
import threading
import queue
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path

# 确保能导入同目录的 mget 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mget
from mget import (
    load_config, netease_search, parse_multi_select,
    search_multi, fmt_duration, SOURCES, BROWSER_FALLBACK, YT_STRATEGIES,
    _validate_proxy, translate_error, _build_dl_opts, download_netease,
)
from proxy_detector import find_best_proxy
from player import PlayerEngine, scan_audio_files, MODE_ORDER, MODE_RANDOM, MODE_REPEAT, MODE_STOP
from streamer import StreamerEngine
import stream_songs

# ════════════════════════════════════════════════════════════
#  配色 & 常量
# ════════════════════════════════════════════════════════════

CLR = {
    "bg":          "#0d0d12",   # 极深蓝黑
    "surface":     "#16161F",   # 卡片/面板
    "surface2":    "#1E1E2A",   # 输入框
    "surface3":    "#262636",   # hover 态
    "border":      "#23242A",   # 分割线
    "text":        "#F0F0F5",   # 主文字 — 微暖白
    "text2":       "#7A7A8E",   # 次要文字
    "text3":       "#55556B",   # 禁用文字
    "accent":      "#4DE8FF",   # 青蓝
    "accent_hover": "#7AEEFF",  # 亮青蓝
    "accent_dim":  "#4DE8FF18", # 半透明青蓝
    "success":     "#10B981",   # 翡翠绿
    "warning":     "#F59E0B",   # 琥珀
    "danger":      "#EF4444",   # 红
    "row_even":    "#1A1A24",   # 交替行-偶
    "row_odd":     "#14141C",   # 交替行-奇
}

FONT = {
    "brand":   ("Microsoft YaHei UI", 20, "bold"),
    "title":   ("Microsoft YaHei UI", 13, "bold"),
    "body":    ("Microsoft YaHei UI", 12),
    "small":   ("Microsoft YaHei UI", 11),
    "tiny":    ("Microsoft YaHei UI", 10),
}


# ════════════════════════════════════════════════════════════
#  配置管理器（GUI 友好的封装）
# ════════════════════════════════════════════════════════════

class ConfigManager:
    """读取/写入 config.yaml，暴露 GUI 需要的字段"""

    def __init__(self):
        self.cfg_path = Path(__file__).parent / "config.yaml"
        self.data = {}
        self.reload()

    def reload(self):
        self.data = self._load_raw()

    def _load_raw(self):
        import yaml
        if not self.cfg_path.exists():
            return {
                "output_dir": os.path.expanduser("~/Music/mget"),
                "audio_format": "mp3",
                "audio_quality": 0,
                "embed_metadata": True,
                "embed_thumbnail": True,
                "search_count": 20,
                "source_priority": ["youtube", "soundcloud", "bilibili"],
                "netease_direct": True,
                "proxy": None,
                "player_mode": 0,
                "stream_mode": 0,
            }
        with open(self.cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("output_dir", os.path.expanduser("~/Music/mget"))
        data.setdefault("audio_format", "mp3")
        data.setdefault("audio_quality", 0)
        data.setdefault("embed_metadata", True)
        data.setdefault("embed_thumbnail", True)
        data.setdefault("search_count", 20)
        data.setdefault("source_priority", ["youtube", "soundcloud", "bilibili"])
        data.setdefault("netease_direct", True)
        data.setdefault("proxy", None)
        data.setdefault("player_mode", MODE_ORDER)
        data.setdefault("stream_mode", MODE_ORDER)
        return data

    def save(self):
        import yaml
        data = {
            "output_dir": self.data["output_dir"],
            "audio_format": self.data["audio_format"],
            "audio_quality": self.data["audio_quality"],
            "embed_metadata": self.data["embed_metadata"],
            "embed_thumbnail": self.data["embed_thumbnail"],
            "search_count": self.data["search_count"],
            "source_priority": self.data["source_priority"],
            "netease_direct": self.data.get("netease_direct", True),
            "player_mode": self.data.get("player_mode", MODE_ORDER),
            "stream_mode": self.data.get("stream_mode", MODE_ORDER),
        }
        if self.data.get("proxy"):
            data["proxy"] = self.data["proxy"]
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

    def get_full_config(self):
        """返回 mget.load_config 兼容的完整 dict"""
        cfg = dict(self.data)
        cfg["output_dir"] = os.path.expanduser(cfg["output_dir"])
        os.makedirs(cfg["output_dir"], exist_ok=True)
        # 代理处理（与 mget.load_config 一致：检测 + 验证）
        proxy = cfg.get("proxy")
        if proxy == "__auto__" or not proxy:
            detected = find_best_proxy()
            if detected and _validate_proxy(detected["url"]):
                cfg["proxy"] = detected["url"]
            else:
                cfg["proxy"] = None
        return cfg


# ════════════════════════════════════════════════════════════
#  深色主题样式
# ════════════════════════════════════════════════════════════

def apply_dark_theme(root):
    """为 root 和 ttk 控件配置深色主题"""
    style = ttk.Style(root)

    # 尝试使用 clam 主题（跨平台一致）
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=CLR["bg"])

    # 全局默认
    style.configure(".", background=CLR["bg"], foreground=CLR["text"], font=FONT["body"])

    # Frame
    style.configure("TFrame", background=CLR["bg"])
    style.configure("Card.TFrame", background=CLR["surface"], relief="flat")

    # Label
    style.configure("TLabel", background=CLR["bg"], foreground=CLR["text"])
    style.configure("Card.TLabel", background=CLR["surface"], foreground=CLR["text"])
    style.configure("Title.TLabel", font=FONT["title"], foreground=CLR["accent"], background=CLR["bg"])
    style.configure("Heading.TLabel", font=FONT["title"], foreground=CLR["text"])
    style.configure("Sub.TLabel", font=FONT["small"], foreground=CLR["text2"])

    # ── Button ──────────────────────────────────────────
    # 次要按钮 — 幽灵风
    style.configure("TButton",
        background=CLR["surface2"], foreground=CLR["text"],
        borderwidth=0, relief="flat", padding=(18, 8),
        font=FONT["body"],
    )
    style.map("TButton",
        background=[("active", CLR["surface3"]), ("disabled", CLR["surface"])],
        foreground=[("active", CLR["text"]), ("disabled", CLR["text3"])],
    )

    # 主要按钮 — 火龙果渐变风
    style.configure("Accent.TButton",
        background=CLR["accent"], foreground="white",
        font=FONT["title"], padding=(22, 10),
        borderwidth=0, relief="flat",
    )
    style.map("Accent.TButton",
        background=[("active", CLR["accent_hover"]), ("disabled", CLR["surface3"])],
        foreground=[("active", "white"), ("disabled", CLR["text3"])],
    )

    # 小按钮
    style.configure("Small.TButton",
        background=CLR["surface2"], foreground=CLR["text2"],
        padding=(10, 5), font=FONT["small"],
        borderwidth=0, relief="flat",
    )
    style.map("Small.TButton",
        background=[("active", CLR["surface3"])],
        foreground=[("active", CLR["text"])],
    )

    # ── Entry ────────────────────────────────────────────
    style.configure("TEntry",
        fieldbackground=CLR["surface2"], foreground=CLR["text"],
        borderwidth=0, relief="flat", padding=(14, 10),
        insertcolor=CLR["accent"],
    )
    style.map("TEntry",
        fieldbackground=[("focus", CLR["surface3"])],
    )

    # ── Combobox ─────────────────────────────────────────
    style.configure("TCombobox",
        fieldbackground=CLR["surface2"], background=CLR["surface2"],
        foreground=CLR["text"], arrowcolor=CLR["text2"],
        borderwidth=0, relief="flat", padding=(10, 8),
    )
    style.map("TCombobox",
        fieldbackground=[("readonly", CLR["surface2"]), ("active", CLR["surface3"])],
        foreground=[("readonly", CLR["text"])],
    )
    root.option_add("*TCombobox*Listbox.background", CLR["surface2"])
    root.option_add("*TCombobox*Listbox.foreground", CLR["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", CLR["accent_dim"])
    root.option_add("*TCombobox*Listbox.selectForeground", CLR["text"])

    # ── Checkbutton ──────────────────────────────────────
    style.configure("TCheckbutton",
        background=CLR["surface"], foreground=CLR["text"],
        font=FONT["body"],
    )
    style.map("TCheckbutton",
        background=[("active", CLR["surface"])],
        foreground=[("active", CLR["accent"])],
    )

    # ── Progressbar ──────────────────────────────────────
    style.configure("TProgressbar",
        troughcolor=CLR["surface2"],
        background=CLR["accent"],
        bordercolor=CLR["border"],
        thickness=6,
    )
    style.configure("Success.TProgressbar",
        troughcolor=CLR["surface2"],
        background=CLR["success"],
        thickness=6,
    )

    # ── Treeview ─────────────────────────────────────────
    style.configure("Treeview",
        background=CLR["surface"],
        foreground=CLR["text"],
        fieldbackground=CLR["surface"],
        borderwidth=0,
        font=FONT["body"],
        rowheight=36,
    )
    style.configure("Treeview.Heading",
        background=CLR["surface2"],
        foreground=CLR["text2"],
        font=FONT["small"],
        borderwidth=0,
        padding=(12, 10),
    )
    style.map("Treeview",
        background=[("selected", CLR["accent_dim"])],
        foreground=[("selected", CLR["accent"])],
    )
    style.map("Treeview.Heading",
        background=[("active", CLR["surface3"])],
    )

    # ── Notebook (标签页) ───────────────────────────────
    style.configure("TNotebook",
        background=CLR["bg"],
        borderwidth=0,
        tabmargins=(0, 2, 0, 0),
    )
    style.configure("TNotebook.Tab",
        background=CLR["surface"],
        foreground=CLR["text2"],
        font=FONT["body"],
        padding=(20, 10),
        borderwidth=0,
    )
    style.map("TNotebook.Tab",
        background=[("selected", CLR["surface2"]), ("active", CLR["surface3"])],
        foreground=[("selected", CLR["accent"]), ("active", CLR["text"])],
    )

    # ── Separator ────────────────────────────────────────
    style.configure("TSeparator", background=CLR["border"])

    # ── Scrollbar ────────────────────────────────────────
    style.configure("TScrollbar",
        background=CLR["surface2"],
        troughcolor=CLR["bg"],
        borderwidth=0,
        arrowsize=0,
        width=10,
    )
    style.map("TScrollbar",
        background=[("active", CLR["surface3"]), ("pressed", CLR["accent"])],
    )

    # ── Scale ────────────────────────────────────────────
    style.configure("TScale",
        background=CLR["surface2"],
        troughcolor=CLR["surface2"],
        borderwidth=0,
    )

    return style


# ════════════════════════════════════════════════════════════
#  搜索结果行数据类
# ════════════════════════════════════════════════════════════

class SongRow:
    """Treeview 中每行的数据"""
    __slots__ = ("checked", "data")
    def __init__(self, data):
        self.checked = False
        self.data = data  # 来自 netease_search 的 dict


# ════════════════════════════════════════════════════════════
#  主应用
# ════════════════════════════════════════════════════════════

class MgetApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Pitaya 音乐下载器")
        # 加载火龙果图标
        icon_path = Path(__file__).parent / "pitaya_icon.ico"
        if icon_path.exists():
            try:
                self.root.iconbitmap(str(icon_path))
            except Exception:
                pass
        self.root.geometry("960x760")
        self.root.minsize(700, 560)

        # 居中
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 960) // 2
        y = (sh - 760) // 2
        self.root.geometry(f"960x760+{x}+{y}")

        # 状态
        self.cfg = ConfigManager()
        self.songs = []          # list[SongRow]
        self.search_thread = None
        self.download_queue = queue.Queue()
        self.downloading = False
        self._proxy_detecting = False  # 代理检测进行中（防重复点击）
        self.dl_widgets = {}     # {song_name: {progress, label, status}}
        self._preview_mode = False  # 试听模式：下载完成后自动播放
        self._progress_dragging = False  # 进度条拖动中，暂停 tick 更新

        # 流播放状态
        self.streamer = None
        self._vlc_ok = False
        self.stream_results = []
        self.stream_searching = False
        self.stream_search_thread = None
        self._stream_progress_dragging = False
        self._stream_current_idx = -1      # 当前播放在线曲库第几首
        self._stream_mode = MODE_ORDER     # 顺序/随机/单曲循环
        self._stream_mini_frame = None     # 在线曲库 mini bar 引用

        # 播放器状态
        self.player = None
        self._player_bar = None
        self._player_info_lbl = None
        self._player_time_lbl = None
        self._player_progress = None
        self._player_play_btn = None
        self._player_mode_btn = None
        self._player_vol_scale = None
        self._playlist_tree = None
        self._playlist_items = []

        # 样式
        self.style = apply_dark_theme(root)

        # 先初始化播放器 (pygame mixer 需在主线程，且在 _build_ui 之前)
        self.player = PlayerEngine(
            on_tick=lambda pos, total: self.root.after(0, self._on_player_tick, pos, total),
            on_song_end=lambda: self.root.after(0, self._on_song_end),
        )
        self._restore_modes()

        # 流播引擎 (python-vlc)
        try:
            self.streamer = StreamerEngine(
                on_tick=lambda pos, total: self.root.after(0, self._on_stream_tick, pos, total),
                on_song_end=lambda: self.root.after(0, self._on_stream_end),
                on_error=lambda msg: self.root.after(0, self._on_stream_error, msg),
            )
            self._vlc_ok = True
        except Exception:
            self.streamer = None
            self._vlc_ok = False

        # 构建 UI
        self._build_ui()

        # 窗口关闭清理
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # 启动时扫描下载目录
        self._scan_and_add_to_playlist()

        # 定时检查下载进度
        self._poll_download()

        # 定时刷新播放器 UI
        self._poll_player()

    # ── UI 构建 ────────────────────────────────────────────

    def _build_ui(self):
        # ═══════════════════════════════════════════════
        #  顶部标题栏 — 极简紧凑
        # ═══════════════════════════════════════════════
        title_bar = tk.Frame(self.root, bg=CLR["bg"])
        title_bar.pack(fill=tk.X, padx=16, pady=(12, 4))

        title_lbl = tk.Label(title_bar, text="🐉  Pitaya",
                             font=FONT["brand"],
                             fg=CLR["accent"], bg=CLR["bg"])
        title_lbl.pack(side=tk.LEFT)

        title_suffix = tk.Label(title_bar, text="音乐下载器",
                                font=FONT["brand"],
                                fg=CLR["text"], bg=CLR["bg"])
        title_suffix.pack(side=tk.LEFT, padx=(6, 0))

        version_lbl = tk.Label(title_bar, text="by 火龙果不是我偷的",
                               font=FONT["tiny"],
                               fg=CLR["text3"], bg=CLR["bg"])
        version_lbl.pack(side=tk.RIGHT, pady=(6, 0))

        # 分隔线
        sep = tk.Frame(self.root, bg=CLR["border"], height=1)
        sep.pack(fill=tk.X, padx=16, pady=(4, 0))

        # ═══════════════════════════════════════════════
        #  底部播放器栏 (必须先 pack)
        # ═══════════════════════════════════════════════
        self._build_player_bar()

        # ═══════════════════════════════════════════════
        #  标签页
        # ═══════════════════════════════════════════════
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=(8, 12))

        self._build_stream_tab()
        self._build_search_tab()
        self._build_playlist_tab()
        self._build_settings_tab()

        # tab 切换时控制底部播放器栏显隐
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event=None):
        """切 tab 时自动显示/隐藏底部播放器栏"""
        idx = self.notebook.index("current")
        if idx == 0:  # 在线曲库(首 tab) → 隐藏底部本地播放器栏
            self._player_bar.pack_forget()
        else:  # 其他 tab → 显示底部播放器栏
            self._player_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_search_tab(self):
        """搜索下载标签页"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  搜索下载  ")

        # ── 搜索栏 ──
        search_frame = ttk.Frame(tab, style="Card.TFrame")
        search_frame.pack(fill=tk.X, padx=10, pady=(10, 8))

        # 放大镜图标
        icon_lbl = ttk.Label(search_frame, text="🔍", font=("Segoe UI Symbol", 14),
                             background=CLR["surface"])
        icon_lbl.pack(side=tk.LEFT, padx=(12, 4), pady=8)

        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var,
                                       font=FONT["body"])
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), pady=8)
        self.search_entry.bind("<Return>", lambda e: self._do_search())
        self.search_entry.insert(0, "")

        # 占位文字效果
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        self._placeholder_active = False

        self.search_btn = ttk.Button(search_frame, text="搜索",
                                      style="Accent.TButton",
                                      command=self._do_search)
        self.search_btn.pack(side=tk.RIGHT, padx=(4, 4), pady=6)

        # ── 结果表格 ──
        table_frame = ttk.Frame(tab, style="Card.TFrame")
        # NOTE: 打包延后到本方法末尾统一执行（弹性控件必须最后入队，见末尾）。

        columns = ("sel", "name", "artists", "album", "duration")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings",
                                  selectmode="extended")

        self.tree.heading("sel", text="")
        self.tree.heading("name", text="歌名")
        self.tree.heading("artists", text="歌手")
        self.tree.heading("album", text="专辑")
        self.tree.heading("duration", text="时长")

        self.tree.column("sel", width=32, anchor=tk.CENTER, stretch=False)
        self.tree.column("name", width=220, minwidth=120)
        self.tree.column("artists", width=140, minwidth=80)
        self.tree.column("album", width=160, minwidth=80)
        self.tree.column("duration", width=60, anchor=tk.CENTER, stretch=False)

        # 滚动条
        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 点击表头/行切换勾选
        self.tree.bind("<ButtonRelease-1>", self._on_tree_click)
        # 双击试听
        self.tree.bind("<Double-1>", lambda e: self._preview_selected())
        # 右键菜单
        self.tree.bind("<Button-3>", self._on_right_click)

        # ── 操作按钮栏 ──
        btn_frame = ttk.Frame(tab)
        # NOTE: 打包延后到本方法末尾统一执行（side=BOTTOM）。

        self.preview_btn = ttk.Button(btn_frame, text="🎵 试听选中",
                                       command=self._preview_selected)
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.select_all_btn = ttk.Button(btn_frame, text="☑ 全选",
                                          command=self._toggle_select_all)
        self.select_all_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.invert_btn = ttk.Button(btn_frame, text="↔ 反选",
                                      command=self._invert_selection)
        self.invert_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.download_btn = ttk.Button(btn_frame, text="⬇ 下载选中",
                                        style="Accent.TButton",
                                        command=self._download_selected)
        self.download_btn.pack(side=tk.LEFT)

        # 清空
        self.clear_btn = ttk.Button(btn_frame, text="清空列表",
                                     command=self._clear_results)
        self.clear_btn.pack(side=tk.RIGHT, padx=(0, 0))

        # ── 下载进度面板 ──
        self.progress_frame = ttk.LabelFrame(tab, text=" 下载进度 ",
                                              padding=(10, 6))
        # NOTE: 打包延后到本方法末尾统一执行（side=BOTTOM）。

        self.progress_canvas = tk.Canvas(self.progress_frame,
                                          bg=CLR["bg"],
                                          highlightthickness=0,
                                          height=0)  # collapsed until tasks arrive; _fit_progress_canvas expands it
        self.progress_inner = ttk.Frame(self.progress_canvas)
        self.progress_scroll = ttk.Scrollbar(self.progress_frame, orient=tk.VERTICAL,
                                              command=self.progress_canvas.yview)
        self.progress_canvas.configure(yscrollcommand=self.progress_scroll.set)

        self.progress_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.progress_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.progress_window = self.progress_canvas.create_window(
            (0, 0), window=self.progress_inner, anchor=tk.NW, tags="inner")
        self.progress_inner.bind("<Configure>",
            lambda e: self.progress_canvas.configure(
                scrollregion=self.progress_canvas.bbox("all")))
        self.progress_canvas.bind("<Configure>",
            lambda e: self.progress_canvas.itemconfig(
                self.progress_window, width=e.width))

        # ── 状态栏 ──
        status_frame = ttk.Frame(tab, style="Card.TFrame")
        # ── 打包顺序（关键）─────────────────────────────────────
        # tk pack 按调用顺序“先到先得”地分配空间：先打包的控件先拿到请求尺寸，
        # 空间不足时靠后的控件会被压到 0 高。此前结果表格（expand=True，请求高
        # 约 404px）排在进度面板之前，把进度面板挤成 5px、状态栏挤成未映射，
        # 于是“下载进度条看不到”。修复：底部三块先以 side=BOTTOM 占位，弹性的
        # 结果表格最后打包，只吃剩余空间。视觉自上而下不变：
        # 搜索栏 / 结果表格 / 按钮栏 / 进度面板 / 状态栏。
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        self.progress_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(4, 8))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 4))
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        self.status_var = tk.StringVar(value="就绪")
        self.status_lbl = ttk.Label(status_frame, textvariable=self.status_var,
                                     style="Sub.TLabel")
        self.status_lbl.pack(side=tk.LEFT, padx=12, pady=6)

        self.dir_var = tk.StringVar(
            value=f"下载目录: {os.path.expanduser(self.cfg.data.get('output_dir', '~/Music/mget'))}")
        self.dir_lbl = ttk.Label(status_frame, textvariable=self.dir_var,
                                  style="Sub.TLabel")
        self.dir_lbl.pack(side=tk.RIGHT, padx=12, pady=6)

    def _build_settings_tab(self):
        """设置标签页"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  设置  ")

        # 使用 canvas + scroll 支持小窗口滚动
        canvas = tk.Canvas(tab, bg=CLR["bg"], highlightthickness=0)
        scroll = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=canvas.yview)
        settings_inner = ttk.Frame(canvas)

        settings_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=settings_inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=scroll.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 绑定宽度
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(canvas.find_withtag("all")[0] if canvas.find_withtag("all") else None,
                                        width=e.width) if canvas.find_withtag("all") else None)

        # ── 下载设置组 ──
        self._add_section(settings_inner, "下载设置")
        row_frame = ttk.Frame(settings_inner)
        row_frame.pack(fill=tk.X, padx=20, pady=(8, 4))

        ttk.Label(row_frame, text="下载目录").pack(side=tk.LEFT)
        self.dl_dir_var = tk.StringVar(
            value=os.path.expanduser(self.cfg.data.get("output_dir", "~/Music/mget")))
        dir_entry = ttk.Entry(row_frame, textvariable=self.dl_dir_var, width=40)
        dir_entry.pack(side=tk.LEFT, padx=(8, 4), fill=tk.X, expand=True)
        ttk.Button(row_frame, text="📂", style="Small.TButton",
                   command=self._browse_dir).pack(side=tk.LEFT)

        # 格式 & 音质
        fmt_row = ttk.Frame(settings_inner)
        fmt_row.pack(fill=tk.X, padx=20, pady=4)

        ttk.Label(fmt_row, text="输出格式").pack(side=tk.LEFT)
        self.fmt_var = tk.StringVar(value=self.cfg.data.get("audio_format", "mp3"))
        fmt_combo = ttk.Combobox(fmt_row, textvariable=self.fmt_var,
                                  values=["best", "mp3", "m4a", "opus", "flac", "wav"],
                                  width=8, state="readonly")
        fmt_combo.pack(side=tk.LEFT, padx=(8, 24))

        ttk.Label(fmt_row, text="音质").pack(side=tk.LEFT)
        self.quality_var = tk.StringVar(
            value="最高" if self.cfg.data.get("audio_quality", 0) == 0 else str(self.cfg.data.get("audio_quality", 0)))
        qual_combo = ttk.Combobox(fmt_row, textvariable=self.quality_var,
                                   values=["最高", "192k", "128k"],
                                   width=8, state="readonly")
        qual_combo.pack(side=tk.LEFT, padx=(8, 24))

        ttk.Label(fmt_row, text="结果数").pack(side=tk.LEFT)
        self.count_var = tk.StringVar(value=str(self.cfg.data.get("search_count", 20)))
        count_combo = ttk.Combobox(fmt_row, textvariable=self.count_var,
                                    values=["5", "10", "15", "20", "30", "50"],
                                    width=5, state="readonly")
        count_combo.pack(side=tk.LEFT, padx=(8, 0))

        # 嵌入选项
        chk_row = ttk.Frame(settings_inner)
        chk_row.pack(fill=tk.X, padx=20, pady=4)

        self.embed_meta_var = tk.BooleanVar(
            value=self.cfg.data.get("embed_metadata", True))
        ttk.Checkbutton(chk_row, text="嵌入歌曲信息（歌手/专辑）",
                        variable=self.embed_meta_var).pack(side=tk.LEFT, padx=(0, 20))

        self.embed_thumb_var = tk.BooleanVar(
            value=self.cfg.data.get("embed_thumbnail", True))
        ttk.Checkbutton(chk_row, text="嵌入封面图",
                        variable=self.embed_thumb_var).pack(side=tk.LEFT)

        # ── 音源设置组 ──
        self._add_section(settings_inner, "音源优先级")
        src_note = ttk.Label(settings_inner,
                              text="按顺序尝试，失败自动回退下一个",
                              style="Sub.TLabel")
        src_note.pack(padx=20, pady=(4, 2), anchor=tk.W)

        src_frame = ttk.Frame(settings_inner)
        src_frame.pack(fill=tk.X, padx=20, pady=4)

        self.src_vars = {}
        self.src_labels = {}
        priority = self.cfg.data.get("source_priority", ["youtube", "soundcloud", "bilibili"])
        all_srcs = ["youtube", "soundcloud", "bilibili"]

        for i, src in enumerate(all_srcs):
            src_info = SOURCES.get(src, {})
            name = src_info.get("name", src)
            proxy_tag = "🔗" if src_info.get("needs_proxy") else "🏠"
            label = f"{proxy_tag} {name}"
            var = tk.BooleanVar(value=src in priority)
            cb = ttk.Checkbutton(src_frame, text=label, variable=var)
            cb.pack(side=tk.LEFT, padx=(0, 16))
            self.src_vars[src] = var
            self.src_labels[src] = label

        # 网易云直链优先开关
        netease_row = ttk.Frame(settings_inner)
        netease_row.pack(fill=tk.X, padx=20, pady=(2, 4))
        self.netease_direct_var = tk.BooleanVar(
            value=self.cfg.data.get("netease_direct", True))
        ttk.Checkbutton(netease_row, text="🚀 优先网易云直链下载（免费歌曲，无需代理）",
                        variable=self.netease_direct_var).pack(side=tk.LEFT)

        # ── 代理设置组 ──
        self._add_section(settings_inner, "代理设置")

        proxy_row = ttk.Frame(settings_inner)
        proxy_row.pack(fill=tk.X, padx=20, pady=4)

        ttk.Label(proxy_row, text="代理地址").pack(side=tk.LEFT)
        current_proxy = self.cfg.data.get("proxy", "")
        if not current_proxy:
            current_proxy = "__auto__"
        self.proxy_var = tk.StringVar(value=current_proxy)
        proxy_combo = ttk.Combobox(proxy_row, textvariable=self.proxy_var,
                                    values=["__auto__",
                                            "http://127.0.0.1:7890",
                                            "socks5://127.0.0.1:10808",
                                            "http://127.0.0.1:10809",
                                            "socks5://127.0.0.1:1080",
                                            ""],
                                    width=28)
        proxy_combo.pack(side=tk.LEFT, padx=(8, 4), fill=tk.X, expand=True)

        self.detect_btn = ttk.Button(proxy_row, text="检测",
                                      command=self._detect_proxy)
        self.detect_btn.pack(side=tk.LEFT, padx=(4, 0))

        # ── 按钮 ──
        btn_row = ttk.Frame(settings_inner)
        btn_row.pack(fill=tk.X, padx=20, pady=(16, 20))

        ttk.Button(btn_row, text="💾 保存设置", style="Accent.TButton",
                   command=self._save_settings).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="↺ 恢复默认",
                   command=self._reset_settings).pack(side=tk.LEFT)

    def _add_section(self, parent, title):
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=14, pady=(16, 6))
        ttk.Label(parent, text=title, style="Heading.TLabel").pack(padx=20, anchor=tk.W)

    # ── 在线曲库标签页 ────────────────────────────────────

    def _build_stream_tab(self):
        """在线曲库 — 网易云搜索 → 流式播放"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  在线曲库  ")

        if not self._vlc_ok:
            notice = ttk.Label(tab,
                text="需要安装 VLC media player\nhttps://www.videolan.org/vlc/",
                style="Sub.TLabel", justify=tk.CENTER)
            notice.pack(expand=True)
            return

        # ── 搜索栏 ──
        search_frame = ttk.Frame(tab, style="Card.TFrame")
        search_frame.pack(fill=tk.X, padx=10, pady=(10, 8))

        icon_lbl = ttk.Label(search_frame, text="🔍", font=("Segoe UI Symbol", 14),
                             background=CLR["surface"])
        icon_lbl.pack(side=tk.LEFT, padx=(12, 4), pady=8)

        self.stream_search_var = tk.StringVar()
        self.stream_search_entry = ttk.Entry(search_frame,
            textvariable=self.stream_search_var, font=FONT["body"])
        self.stream_search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True,
            padx=(0, 4), pady=8)
        self.stream_search_entry.bind("<Return>", lambda e: self._do_stream_search())

        self.stream_search_btn = ttk.Button(search_frame, text="搜索",
            style="Accent.TButton", command=self._do_stream_search)
        self.stream_search_btn.pack(side=tk.RIGHT, padx=(4, 4), pady=6)

        # ── 结果表格 ──
        table_frame = ttk.Frame(tab, style="Card.TFrame")
        # NOTE: 打包延后到本方法末尾统一执行（side=BOTTOM）。

        columns = ("num", "name", "artists", "album", "duration")
        self.stream_tree = ttk.Treeview(table_frame, columns=columns,
            show="headings", selectmode="browse")

        self.stream_tree.heading("num", text="#")
        self.stream_tree.heading("name", text="歌名")
        self.stream_tree.heading("artists", text="歌手")
        self.stream_tree.heading("album", text="专辑")
        self.stream_tree.heading("duration", text="时长")

        self.stream_tree.column("num", width=36, anchor=tk.CENTER, stretch=False)
        self.stream_tree.column("name", width=220, minwidth=120)
        self.stream_tree.column("artists", width=140, minwidth=80)
        self.stream_tree.column("album", width=160, minwidth=80)
        self.stream_tree.column("duration", width=60, anchor=tk.CENTER, stretch=False)

        scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL,
            command=self.stream_tree.yview)
        self.stream_tree.configure(yscrollcommand=scroll.set)
        self.stream_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.stream_tree.bind("<Double-1>", lambda e: self._stream_play_selected())
        self.stream_tree.tag_configure("stream_even", background=CLR["row_even"])
        self.stream_tree.tag_configure("stream_odd", background=CLR["row_odd"])

        # ── 操作按钮栏 ──
        btn_frame = ttk.Frame(tab)
        # NOTE: 打包延后到本方法末尾统一执行（side=BOTTOM）。

        self.stream_play_btn = ttk.Button(btn_frame, text="▶ 在线播放",
            style="Accent.TButton", command=self._stream_play_selected)
        self.stream_play_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stream_dl_btn = ttk.Button(btn_frame, text="⬇ 下载",
            command=self._stream_download_selected)
        self.stream_dl_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stream_stop_btn = ttk.Button(btn_frame, text="🛑 停止",
            command=self._stream_stop)
        self.stream_stop_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stream_clear_btn = ttk.Button(btn_frame, text="清空列表",
            command=self._stream_clear)
        self.stream_clear_btn.pack(side=tk.RIGHT, padx=(0, 0))

        self.stream_curated_btn = ttk.Button(btn_frame, text="⭐ 精选",
            command=self._load_curated)
        self.stream_curated_btn.pack(side=tk.RIGHT, padx=(0, 6))

        # ── Mini 播放栏 ──
        mini_frame = ttk.Frame(tab, style="Card.TFrame")
        # NOTE: 打包延后到本方法末尾统一执行（side=BOTTOM）。
        self._stream_mini_frame = mini_frame

        self.stream_info_lbl = ttk.Label(mini_frame, text="♫ 未在播放",
            font=FONT["body"], background=CLR["surface"])
        self.stream_info_lbl.pack(side=tk.TOP, anchor=tk.W, padx=12, pady=(6, 0))

        # 进度
        prog_row = ttk.Frame(mini_frame, style="Card.TFrame")
        prog_row.pack(fill=tk.X, padx=12, pady=(4, 0))

        self.stream_time_lbl = ttk.Label(prog_row, text="--:-- / --:--",
            font=FONT["small"], background=CLR["surface"])
        self.stream_time_lbl.pack(side=tk.RIGHT, pady=(2, 0))

        self.stream_progress = ttk.Scale(prog_row, from_=0, to=100,
            orient=tk.HORIZONTAL)
        self.stream_progress.set(0)
        self.stream_progress.bind("<ButtonPress-1>", self._on_stream_progress_press)
        self.stream_progress.bind("<ButtonRelease-1>", self._on_stream_progress_release)
        self.stream_progress.pack(side=tk.LEFT, fill=tk.X, expand=True,
            padx=(0, 8), pady=(0, 4))

        # 控制
        ctrl_row = ttk.Frame(mini_frame, style="Card.TFrame")
        ctrl_row.pack(fill=tk.X, padx=12, pady=(2, 6))

        self.stream_prev_btn = ttk.Button(ctrl_row, text="⏮",
            style="Small.TButton", command=self._stream_prev)
        self.stream_prev_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stream_pp_btn = ttk.Button(ctrl_row, text="▶ 播放",
            style="Small.TButton", command=self._stream_toggle_play)
        self.stream_pp_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stream_next_btn = ttk.Button(ctrl_row, text="⏭",
            style="Small.TButton", command=self._stream_next)
        self.stream_next_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stream_mode_btn = ttk.Button(ctrl_row, text="🔁 顺序",
            style="Small.TButton", command=self._stream_toggle_mode)

        self.stream_mode_btn.pack(side=tk.LEFT, padx=(0, 8))
        # 按启动时恢复的模式刷新按钮初始文案
        _SMODE_TEXT = {MODE_ORDER: "🔁 顺序", MODE_RANDOM: "🔀 随机",
                       MODE_REPEAT: "🔂 单曲", MODE_STOP: "⏹ 一遍"}
        self.stream_mode_btn.configure(
            text=_SMODE_TEXT.get(self._stream_mode, _SMODE_TEXT[MODE_ORDER]))

        # 单曲循环开关：独立于模式循环，亮色 = 开，灰色 = 关
        self.stream_repeat_btn = tk.Button(ctrl_row, text="🔂",
            font=FONT["small"], fg=CLR["text3"],
            bg=CLR["surface"], activebackground=CLR["surface"],
            activeforeground=CLR["accent"], bd=0, cursor="hand2",
            command=self._stream_toggle_repeat_one)
        self.stream_repeat_btn.configure(
            fg=CLR["accent"] if self._stream_mode == MODE_REPEAT else CLR["text3"])
        self.stream_repeat_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(ctrl_row, text="🔊", font=FONT["small"],
            background=CLR["surface"]).pack(side=tk.LEFT, padx=(0, 4))

        self.stream_vol_scale = ttk.Scale(ctrl_row, from_=0, to=100,
            orient=tk.HORIZONTAL, length=120, command=self._on_stream_volume)
        self.stream_vol_scale.set(80)
        self.stream_vol_scale.pack(side=tk.LEFT)

        # ── 状态栏 ──
        status_frame = ttk.Frame(tab, style="Card.TFrame")
        # ── 打包顺序（关键）─────────────────────────────────────
        # 与「搜索下载」页同理：tk pack 先到先得，弹性的结果表格必须最后打包，
        # 否则会把下方的 Mini 播放栏 / 状态栏挤成 0 高。
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        mini_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(4, 4))
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 4))
        table_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

        self.stream_status_var = tk.StringVar(value="就绪 — 双击歌曲即可在线播放")
        # 开箱即有内容: 启动时载入内置精选歌单
        self._load_curated()
        self.stream_status_lbl = ttk.Label(status_frame,
            textvariable=self.stream_status_var, style="Sub.TLabel")
        self.stream_status_lbl.pack(side=tk.LEFT, padx=12, pady=6)

    # ── 播放器底部栏 ──────────────────────────────────────

    def _build_player_bar(self):
        """窗口底部播放控制栏 — 现代极简"""
        bar = tk.Frame(self.root, bg=CLR["surface"], height=68)
        bar.pack_propagate(False)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        # 左侧：歌曲信息
        left = tk.Frame(bar, bg=CLR["surface"])
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(16, 8))

        self._player_info_lbl = tk.Label(left, text="♫ 未在播放",
                                          font=FONT["body"],
                                          fg=CLR["text"], bg=CLR["surface"])
        self._player_info_lbl.pack(anchor=tk.W, pady=(10, 0))

        # 中间：进度条
        center = tk.Frame(bar, bg=CLR["surface"])
        center.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

        self._player_time_lbl = tk.Label(center, text="00:00 / --:--",
                                          font=FONT["small"],
                                          fg=CLR["text2"], bg=CLR["surface"])
        self._player_time_lbl.pack(side=tk.TOP, anchor=tk.E, pady=(4, 0))

        self._player_progress = ttk.Scale(center, from_=0, to=100,
                                           orient=tk.HORIZONTAL,
                                           command=self._on_progress_drag)
        self._player_progress.set(0)
        self._player_progress.bind("<ButtonPress-1>", self._on_progress_press)
        self._player_progress.bind("<ButtonRelease-1>", self._on_progress_release)
        self._player_progress.pack(fill=tk.X, pady=(2, 0))

        # 右侧：控制按钮
        ctrl = tk.Frame(bar, bg=CLR["surface"])
        ctrl.pack(side=tk.RIGHT, padx=(0, 16), pady=12)

        btn_cfg = dict(font=FONT["small"], fg=CLR["text2"],
                       bg=CLR["surface"], activebackground=CLR["surface"],
                       activeforeground=CLR["accent"],
                       bd=0, cursor="hand2")

        tk.Button(ctrl, text="⏮", command=self._play_prev, **btn_cfg).pack(side=tk.LEFT, padx=4)

        self._player_play_btn = tk.Button(ctrl, text="▶", font=FONT["title"],
                                           fg=CLR["accent"], bg=CLR["surface"],
                                           activebackground=CLR["surface"],
                                           activeforeground=CLR["accent_hover"],
                                           bd=0, cursor="hand2",
                                           command=self._play_pause)
        self._player_play_btn.pack(side=tk.LEFT, padx=6)

        tk.Button(ctrl, text="⏭", command=self._play_next, **btn_cfg).pack(side=tk.LEFT, padx=4)

        # 音量
        tk.Label(ctrl, text="🔊", font=FONT["small"],
                 fg=CLR["text3"], bg=CLR["surface"]).pack(side=tk.LEFT, padx=(12, 2))
        self._player_vol_scale = ttk.Scale(ctrl, from_=0, to=100,
                                            orient=tk.HORIZONTAL, length=70,
                                            command=self._set_volume)
        self._player_vol_scale.set(80)
        self._player_vol_scale.pack(side=tk.LEFT)

        # 模式
        MODE_LABELS = {MODE_ORDER: "🔁 顺序", MODE_RANDOM: "🔀 随机",
                       MODE_REPEAT: "🔂 单曲", MODE_STOP: "⏹ 一遍"}
        self._player_mode_btn = tk.Button(ctrl,
                                           text=MODE_LABELS[self.player.mode],
                                           width=9,
                                           command=self._toggle_mode, **btn_cfg)
        self._player_mode_btn.pack(side=tk.LEFT, padx=(12, 0))

        # 打开文件夹
        tk.Button(ctrl, text="📂", command=self._open_output_dir,
                  **btn_cfg).pack(side=tk.LEFT, padx=(8, 0))

        self._player_bar = bar

    # ── 播放列表标签页 ────────────────────────────────────

    def _build_playlist_tab(self):
        """播放列表标签页"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="  播放列表  ")

        # 工具栏
        toolbar = ttk.Frame(tab, style="Card.TFrame")
        toolbar.pack(fill=tk.X, padx=10, pady=(10, 4))

        ttk.Label(toolbar, text="🎵 播放列表",
                  style="Heading.TLabel",
                  background=CLR["surface"]).pack(side=tk.LEFT, padx=12, pady=8)

        ttk.Button(toolbar, text="📂 扫描目录", style="Small.TButton",
                   command=self._scan_and_add_to_playlist).pack(side=tk.RIGHT, padx=(4, 12), pady=6)

        ttk.Button(toolbar, text="🗑 清空", style="Small.TButton",
                   command=self._clear_playlist).pack(side=tk.RIGHT, padx=4, pady=6)

        ttk.Button(toolbar, text="✕ 移除", style="Small.TButton",
                   command=self._remove_from_playlist).pack(side=tk.RIGHT, padx=4, pady=6)

        # 列表
        list_frame = ttk.Frame(tab, style="Card.TFrame")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        columns = ("idx", "title", "artists")
        self._playlist_tree = ttk.Treeview(list_frame, columns=columns,
                                            show="headings", selectmode="browse")

        self._playlist_tree.heading("idx", text="#")
        self._playlist_tree.heading("title", text="歌名")
        self._playlist_tree.heading("artists", text="歌手")

        self._playlist_tree.column("idx", width=36, anchor=tk.CENTER, stretch=False)
        self._playlist_tree.column("title", width=240, minwidth=120)
        self._playlist_tree.column("artists", width=160, minwidth=80)

        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                               command=self._playlist_tree.yview)
        self._playlist_tree.configure(yscrollcommand=scroll.set)
        self._playlist_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 双击播放
        self._playlist_tree.bind("<Double-1>", self._on_playlist_double_click)

        # 交替行色
        self._playlist_tree.tag_configure("pl_even", background=CLR["row_even"])
        self._playlist_tree.tag_configure("pl_odd", background=CLR["row_odd"])
        self._playlist_tree.tag_configure("pl_current",
                                           background=CLR["accent"],
                                           foreground="#000000")

    # ── 播放列表操作 ──────────────────────────────────────

    def _scan_and_add_to_playlist(self):
        """扫描下载目录，将音频文件加入播放列表"""
        out_dir = os.path.expanduser(self.cfg.data.get("output_dir", "~/Music/mget"))
        songs = scan_audio_files(out_dir)
        added = 0
        for s in songs:
            if self.player.add_song(s["path"], s["title"], s["artists"]):
                added += 1
        self._refresh_playlist_display()
        if added:
            self._set_status(f"已添加 {added} 首到播放列表")
        else:
            self._set_status("播放列表已是最新")

    def _refresh_playlist_display(self):
        """刷新播放列表 Treeview"""
        if not self._playlist_tree:
            return
        for item in self._playlist_tree.get_children():
            self._playlist_tree.delete(item)

        pl = self.player.get_playlist()
        self._playlist_items = pl
        cur = self.player.current_index

        for i, s in enumerate(pl):
            tag = "pl_current" if i == cur else ("pl_even" if i % 2 == 0 else "pl_odd")
            self._playlist_tree.insert("", tk.END, iid=str(i),
                                        values=(i + 1, s["title"], s["artists"]),
                                        tags=(tag,))

    def _clear_playlist(self):
        self.player.clear_playlist()
        self._refresh_playlist_display()
        self._player_info_lbl.configure(text="♫ 未在播放")
        self._player_play_btn.configure(text="▶")
        self._player_progress.set(0)
        self._player_time_lbl.configure(text="00:00 / --:--")

    def _remove_from_playlist(self):
        sel = self._playlist_tree.selection()
        if not sel:
            self._set_status("请先在播放列表中选中歌曲", "warning")
            return
        idx = int(sel[0])
        self.player.remove_song(idx)
        self._refresh_playlist_display()
        self._set_status("已移除")

    def _on_playlist_double_click(self, event):
        item = self._playlist_tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        if idx < len(self._playlist_items):
            self._stop_streamer()  # 播放列表起播 → 停在线流播，防重叠
            self.player.play_index(idx)
            self._refresh_playlist_display()
            self._update_player_bar_state()

    # ── 播放器交互 ────────────────────────────────────────

    def _stop_streamer(self):
        """停止在线流播并复位 mini 栏 — 任何本地起播前调用，防双引擎重叠出声"""
        if self.streamer and not self.streamer.is_stopped():
            self.streamer.stop()
            self._reset_stream_player_bar()

    def _play_pause(self):
        if self.player.is_paused():
            self.player.play_pause()
            self._player_play_btn.configure(text="⏸")
        elif self.player.is_playing():
            self.player.play_pause()
            self._player_play_btn.configure(text="▶")
        else:
            # 停止流播（避免音频重叠）
            self._stop_streamer()
            # 未在播放，尝试播放第一首
            if self.player.playlist:
                if self.player.play_pause():
                    self._player_play_btn.configure(text="⏸")
                    self._update_player_bar_state()
                    self._refresh_playlist_display()
            else:
                self._set_status("播放列表为空，请先下载歌曲", "warning")

    def _play_next(self):
        self._stop_streamer()  # 本地起播/切歌 → 停在线流播，防重叠
        self.player.next()
        self._update_player_bar_state()
        self._refresh_playlist_display()

    def _play_prev(self):
        self._stop_streamer()
        self.player.prev()
        self._update_player_bar_state()
        self._refresh_playlist_display()

    def _on_song_end(self):
        """歌曲自然结束时自动切歌"""
        if self.player.mode == MODE_REPEAT:
            # 单曲循环：重播当前
            cur = self.player.current_song()
            if cur:
                self.player.play_index(self.player.current_index)
        else:
            self.player.next()
        self._update_player_bar_state()
        self._refresh_playlist_display()

    def _on_player_tick(self, pos, total):
        """播放器 tick 回调 — 更新进度条和时间（拖动中跳过进度条写入）"""
        if self.player.is_playing():
            self._player_play_btn.configure(text="⏸")
        elif self.player.is_paused():
            self._player_play_btn.configure(text="▶")

        cur_song = self.player.current_song()
        if cur_song:
            label = cur_song["title"]
            if cur_song["artists"]:
                label += f" — {cur_song['artists']}"
            if len(label) > 45:
                label = label[:43] + "..."
            self._player_info_lbl.configure(text=f"♫ {label}")
        else:
            self._player_info_lbl.configure(text="♫ 未在播放")

        if total > 0:
            if not self._progress_dragging:
                self._player_progress.configure(to=total)
                self._player_progress.set(min(pos, total))
            self._player_time_lbl.configure(
                text=f"{self._fmt_time(pos)} / {self._fmt_time(total)}")
        else:
            if not self._progress_dragging:
                self._player_progress.configure(to=100)
                self._player_progress.set(0)
            self._player_time_lbl.configure(
                text=f"{self._fmt_time(pos)} / --:--")

    def _set_volume(self, val):
        """音量滑块回调"""
        vol = float(val) / 100.0
        self.player.set_volume(vol)

    # ── 进度条拖拽 ────────────────────────────────────────

    def _on_progress_press(self, event):
        """拖拽开始：标记拖拽中，暂停 tick 覆盖"""
        self._progress_dragging = True

    def _on_progress_release(self, event):
        """拖拽结束：执行 seek + 恢复 tick"""
        self._progress_dragging = False
        if self.player and not self.player._stopped:
            pos = float(self._player_progress.get())
            if not self.player.seek(pos):
                self._set_status("该格式不支持跳转（可尝试 MP3 格式）", "warning")

    def _on_progress_drag(self, val):
        """拖拽中实时更新时间标签"""
        if self._progress_dragging:
            pos = float(val)
            total = self.player.get_duration()
            if total > 0:
                self._player_time_lbl.configure(
                    text=f"{self._fmt_time(pos)} / {self._fmt_time(total)}")

    def _toggle_mode(self):
        """切换播放模式: ORDER → RANDOM → REPEAT → STOP → ORDER"""
        MODE_LABELS = {MODE_ORDER: "🔁 顺序", MODE_RANDOM: "🔀 随机",
                       MODE_REPEAT: "🔂 单曲", MODE_STOP: "⏹ 一遍"}
        MODE_NAMES = {MODE_ORDER: "顺序(列表循环)", MODE_RANDOM: "随机",
                      MODE_REPEAT: "单曲循环", MODE_STOP: "一遍(播完即停)"}
        next_mode = {MODE_ORDER: MODE_RANDOM, MODE_RANDOM: MODE_REPEAT,
                     MODE_REPEAT: MODE_STOP, MODE_STOP: MODE_ORDER}

        new_mode = next_mode[self.player.mode]
        self.player.set_mode(new_mode)
        self._player_mode_btn.configure(text=MODE_LABELS[new_mode])
        self._set_status(f"播放模式: {MODE_NAMES[new_mode]}")

    def _update_player_bar_state(self):
        """根据播放状态更新 UI"""
        cur_song = self.player.current_song()
        if cur_song:
            label = cur_song["title"]
            if cur_song["artists"]:
                label += f" — {cur_song['artists']}"
            if len(label) > 45:
                label = label[:43] + "..."
            self._player_info_lbl.configure(text=f"♫ {label}")

        if self.player.is_playing():
            self._player_play_btn.configure(text="⏸")
        elif self.player.is_paused():
            self._player_play_btn.configure(text="▶")
        else:
            self._player_play_btn.configure(text="▶")
            self._player_info_lbl.configure(text="♫ 未在播放")

    def _poll_player(self):
        """轻量轮询：仅兜底刷新播放按钮状态，进度条由 _on_player_tick 独占"""
        if self.player:
            if self.player.is_playing():
                self._player_play_btn.configure(text="⏸")
            elif self.player.is_paused():
                self._player_play_btn.configure(text="▶")
        self.root.after(500, self._poll_player)

    @staticmethod
    def _fmt_time(seconds):
        """秒 -> mm:ss"""
        s = int(seconds)
        return f"{s // 60}:{s % 60:02d}"

    # ── 在线曲库操作 ──────────────────────────────────────

    def _do_stream_search(self):
        """搜索在线曲库"""
        keyword = self.stream_search_var.get().strip()
        if not keyword:
            self.stream_status_var.set("请输入歌名或歌手")
            return
        if self.stream_searching:
            self.stream_status_var.set("搜索中，请稍候...")
            return
        self.stream_searching = True
        self.stream_status_var.set(f"搜索: {keyword} ...")
        self.stream_search_btn.configure(state="disabled", text="搜索中...")
        for row in self.stream_tree.get_children():
            self.stream_tree.delete(row)
        self.stream_results = []
        self.stream_search_thread = threading.Thread(
            target=self._stream_search_worker, args=(keyword,), daemon=True)
        self.stream_search_thread.start()

    def _stream_search_worker(self, keyword):
        results = netease_search(keyword, limit=20)
        self.root.after(0, self._on_stream_search_done, results, keyword)

    def _on_stream_search_done(self, results, keyword):
        self.stream_searching = False
        self.stream_search_btn.configure(state="normal", text="搜索")
        self.stream_results = list(results)
        if not self.stream_results:
            self.stream_status_var.set(f"未找到「{keyword}」的结果")
            return
        for i, r in enumerate(self.stream_results):
            dur = fmt_duration(r.get("duration", 0))
            tag = "stream_even" if i % 2 == 0 else "stream_odd"
            self.stream_tree.insert("", tk.END, values=(
                i + 1, r.get("name", ""), r.get("artists", ""),
                r.get("album", "") or "", dur), tags=(tag,))
        self.stream_status_var.set(f"共 {len(self.stream_results)} 首 | 双击播放")

    def _load_curated(self):
        """载入内置精选歌单 — 开箱即有内容, 点歌时才联网拉流"""
        self.stream_results = list(stream_songs.get_curated())
        for item in self.stream_tree.get_children():
            self.stream_tree.delete(item)
        for i, r in enumerate(self.stream_results):
            dur = fmt_duration(r.get("duration", 0))
            tag = "stream_even" if i % 2 == 0 else "stream_odd"
            self.stream_tree.insert("", tk.END, values=(
                i + 1, r.get("name", ""), r.get("artists", ""),
                r.get("album", "") or "", dur), tags=(tag,))
        self.stream_status_var.set(
            f"内置精选 {len(self.stream_results)} 首 | 双击在线播放")

    def _stream_play_selected(self):
        """播放选中歌曲"""
        sel = self.stream_tree.selection()
        if not sel:
            self.stream_status_var.set("请先选择一首歌")
            return
        idx = self.stream_tree.index(sel[0])
        if idx >= len(self.stream_results):
            return
        song = self.stream_results[idx]
        url = song.get("preview_url", "")
        if not url:
            self.stream_status_var.set("该歌曲无可播放链接")
            return
        # 停止本地播放（避免音频重叠）
        if self.player and (self.player.is_playing() or self.player.is_paused()):
            self.player.stop()
            self._update_player_bar_state()
        if not self.streamer:
            self.stream_status_var.set("VLC 未就绪")
            return
        self._stream_current_idx = idx
        ok = self.streamer.play_url(url, song.get("name", ""),
            song.get("artists", ""))
        if ok:
            if self._stream_mini_frame:
                self._stream_mini_frame.pack(fill=tk.X, padx=10, pady=(4, 4))
            self.stream_info_lbl.configure(
                text=f"♫ {song.get('name','')} — {song.get('artists','')} [在线]")
            self.stream_pp_btn.configure(text="⏸")
            self.stream_progress.configure(state="normal")
            self.stream_status_var.set(f"正在播放: {song.get('name','')}")
            # 高亮当前行
            for item in self.stream_tree.get_children():
                self.stream_tree.item(item, tags=(item,))
            self.stream_tree.item(sel[0], tags=("playing",))
            self.stream_tree.tag_configure("playing",
                background=CLR["accent"], foreground="#000000")
            # 自动滚动到当前行
            self.stream_tree.see(sel[0])
        else:
            self.stream_status_var.set("播放失败，链接可能已失效")

    def _stream_toggle_play(self):
        """Mini bar 播放/暂停"""
        if not self.streamer:
            return
        if self.streamer.is_stopped():
            self._stream_play_selected()
        else:
            self.streamer.play_pause()
            if self.streamer.is_paused():
                self.stream_pp_btn.configure(text="▶")
            else:
                self.stream_pp_btn.configure(text="⏸")

    def _stream_stop(self):
        """停止流播"""
        if self.streamer:
            self.streamer.stop()
        self._reset_stream_player_bar()
        self.stream_status_var.set("已停止")

    def _stream_clear(self):
        """清空搜索结果"""
        for row in self.stream_tree.get_children():
            self.stream_tree.delete(row)
        self.stream_results = []
        self._stream_stop()
        self.stream_status_var.set("就绪 — 双击搜索到的歌曲即可在线播放")

    def _stream_download_selected(self):
        """在线曲库中下载正在试听的歌曲"""
        sel = self.stream_tree.selection()
        if not sel:
            self.stream_status_var.set("请先选择一首歌")
            return
        if self.downloading:
            self.stream_status_var.set("正在下载中，请等待当前任务完成")
            return

        idx = self.stream_tree.index(sel[0])
        if idx >= len(self.stream_results):
            return

        song = self.stream_results[idx]
        name = song.get("name", "")
        artists = song.get("artists", "")
        query = song.get("search_query", f"{name} {artists}").strip()

        self.downloading = True
        self.dl_widgets.clear()
        for w in self.progress_inner.winfo_children():
            w.destroy()
        self._fit_progress_canvas()

        self.stream_status_var.set(f"下载中: {name} — {artists}")
        self._set_status(f"在线曲库下载: {name}")

        songs_snapshot = [{
            "name": name,
            "artists": artists,
            "query": query,
            "id": song.get("id"),
            "fee": song.get("fee", 0),
            "download_url": song.get("download_url"),
        }]
        thread = threading.Thread(
            target=self._download_worker, args=(songs_snapshot,), daemon=True)
        thread.start()

    def _on_stream_tick(self, pos, total):
        """VLC tick 回调"""
        if self._stream_progress_dragging:
            return
        if total > 0:
            self.stream_progress.configure(to=total)
            self.stream_progress.set(min(pos, total))
            self.stream_time_lbl.configure(
                text=f"{self._fmt_time(pos)} / {self._fmt_time(total)}")
        else:
            self.stream_progress.configure(to=100)
            self.stream_progress.set(0)
            self.stream_time_lbl.configure(text=f"{self._fmt_time(pos)} / --:--")

    def _on_stream_end(self):
        """歌曲自然结束 → 根据模式自动切下一首"""
        # 清除高亮
        for item in self.stream_tree.get_children():
            idx = self.stream_tree.index(item)
            tag = "stream_even" if idx % 2 == 0 else "stream_odd"
            self.stream_tree.item(item, tags=(tag,))
        # 单曲循环/顺序/随机 → 自动下一首
        if self._stream_mode == MODE_REPEAT:
            self._stream_next()   # 单曲循环：_stream_next 内部处理
        elif self.stream_results and self._stream_current_idx >= 0:
            total = len(self.stream_results)
            if self._stream_mode in (MODE_ORDER, MODE_STOP):
                # 顺序 / 一遍：最后一首播完即停
                if self._stream_current_idx + 1 < total:
                    self._stream_next()
                else:
                    self._reset_stream_player_bar()
                    self.stream_status_var.set("列表播放完毕")
            else:
                self._stream_next()
        else:
            self._reset_stream_player_bar()
            self.stream_status_var.set("播放结束")

    def _on_stream_error(self, msg):
        """播放出错"""
        self._reset_stream_player_bar()
        self.stream_status_var.set(msg)

    def _stream_prev(self):
        """播放上一首"""
        if not self.stream_results or self._stream_current_idx < 0:
            return
        total = len(self.stream_results)
        idx = self._stream_current_idx - 1
        if idx < 0:
            idx = total - 1
        items = self.stream_tree.get_children()
        if idx < len(items):
            self.stream_tree.selection_set(items[idx])
            self.stream_tree.see(items[idx])
            self._stream_play_selected()

    def _stream_next(self):
        """播放下一首（顺序/随机/单曲循环）"""
        if not self.stream_results or self._stream_current_idx < 0:
            return
        total = len(self.stream_results)
        if self._stream_mode == MODE_REPEAT:
            idx = self._stream_current_idx
        elif self._stream_mode == MODE_RANDOM:
            import random
            idx = random.randint(0, total - 1)
        elif self._stream_mode == MODE_STOP:
            # 一遍：手动点下一首到末尾即停
            if self._stream_current_idx + 1 >= total:
                self._stream_stop()
                self.stream_status_var.set("列表播放完毕")
                return
            idx = self._stream_current_idx + 1
        else:
            idx = self._stream_current_idx + 1
            if idx >= total:
                idx = 0
        # 选中并播放
        items = self.stream_tree.get_children()
        if idx < len(items):
            self.stream_tree.selection_set(items[idx])
            self.stream_tree.see(items[idx])
            self._stream_play_selected()

    def _stream_toggle_repeat_one(self):
        """单曲循环开关: 开 → MODE_REPEAT，关 → 回顺序"""
        if self._stream_mode == MODE_REPEAT:
            self._stream_mode = MODE_ORDER
            self.stream_repeat_btn.configure(fg=CLR["text3"])
            self.stream_mode_btn.configure(text="🔁 顺序")
            self.stream_status_var.set("单曲循环: 关")
        else:
            self._stream_mode = MODE_REPEAT
            self.stream_repeat_btn.configure(fg=CLR["accent"])
            self.stream_mode_btn.configure(text="🔂 单曲")
            self.stream_status_var.set("单曲循环: 开")

    def _stream_toggle_mode(self):
        """切换在线播放模式: 顺序 → 随机 → 单曲 → 一遍"""
        if self._stream_mode == MODE_ORDER:
            self._stream_mode = MODE_RANDOM
            self.stream_mode_btn.configure(text="🔀 随机")
        elif self._stream_mode == MODE_RANDOM:
            self._stream_mode = MODE_REPEAT
            self.stream_mode_btn.configure(text="🔂 单曲")
        elif self._stream_mode == MODE_REPEAT:
            self._stream_mode = MODE_STOP
            self.stream_mode_btn.configure(text="⏹ 一遍")
        else:
            self._stream_mode = MODE_ORDER
            self.stream_mode_btn.configure(text="🔁 顺序")
        # 同步单曲循环开关按钮的亮灭状态
        self.stream_repeat_btn.configure(
            fg=CLR["accent"] if self._stream_mode == MODE_REPEAT else CLR["text3"])

    def _reset_stream_player_bar(self):
        """重置 mini player bar 到空闲"""
        self.stream_info_lbl.configure(text="♫ 未在播放")
        self.stream_time_lbl.configure(text="--:-- / --:--")
        self.stream_progress.set(0)
        self.stream_pp_btn.configure(text="▶ 播放")

    def _on_stream_progress_press(self, event):
        self._stream_progress_dragging = True

    def _on_stream_progress_release(self, event):
        self._stream_progress_dragging = False
        if self.streamer and not self.streamer.is_stopped():
            pos = self.stream_progress.get()
            self.streamer.seek(float(pos))

    def _on_stream_volume(self, val):
        if self.streamer:
            self.streamer.set_volume(float(val) / 100.0)

    def _restore_modes(self):
        """从配置恢复播放模式到两个引擎 (启动时调用)"""
        self.player.set_mode(int(self.cfg.data.get("player_mode", MODE_ORDER)))
        self._stream_mode = int(self.cfg.data.get("stream_mode", MODE_ORDER))

    def _persist_modes(self):
        """把当前播放模式写回配置，下次启动自动恢复"""
        try:
            self.cfg.data["player_mode"] = self.player.mode
            self.cfg.data["stream_mode"] = self._stream_mode
            self.cfg.save()
        except Exception:
            pass  # 关闭/保存阶段失败不应阻塞窗口销毁

    def _on_close(self):
        """关闭窗口前清理资源"""
        self._persist_modes()
        if self.streamer:
            self.streamer.shutdown()
        self.root.destroy()

    # ── 搜索 ───────────────────────────────────────────────

    def _do_search(self):
        keyword = self.search_var.get().strip()
        if not keyword:
            self._set_status("请输入歌名或歌手", "warning")
            return

        if self.search_thread and self.search_thread.is_alive():
            self._set_status("搜索中，请稍候...", "warning")
            return

        self._set_status(f"搜索: {keyword} ...")
        self.search_btn.configure(state="disabled", text="搜索中...")
        self._clear_results()

        self.search_thread = threading.Thread(
            target=self._search_worker, args=(keyword,), daemon=True)
        self.search_thread.start()

    def _search_worker(self, keyword):
        results = netease_search(keyword, limit=int(self.cfg.data.get("search_count", 10)))
        self.root.after(0, self._on_search_done, results, keyword)

    def _on_search_done(self, results, keyword):
        self.search_btn.configure(state="normal", text="搜索")
        self.songs = [SongRow(r) for r in results]

        if not self.songs:
            self._set_status(f"未找到「{keyword}」的结果", "warning")
            return

        for i, song in enumerate(self.songs):
            d = song.data
            dur = fmt_duration(d.get("duration", 0))
            album = d.get("album", "") or ""
            tag = "  "
            # Display-only marker; fee != 0 means the song cannot use the
            # netease direct link (same gate as mget.download_netease).
            name = d["name"] + (" 【VIP】" if d.get("fee", 0) else "")
            self.tree.insert("", tk.END, iid=str(i),
                             values=(tag, name, d["artists"], album, dur),
                             tags=("even" if i % 2 == 0 else "odd",))

        # 交替行色
        self.tree.tag_configure("even", background=CLR["row_even"])
        self.tree.tag_configure("odd", background=CLR["row_odd"])

        self._set_status(f"共 {len(self.songs)} 首 | 点击勾选 → 下载")
        self.root.after(10, lambda: self.search_entry.focus_set())

    def _clear_results(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.songs.clear()
        self._set_status("就绪")

    # ── 勾选逻辑 ───────────────────────────────────────────

    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        col = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)

        if not item:
            return

        idx = int(item)
        if idx >= len(self.songs):
            return

        # 点击 #0 列 (sel) 切换勾选
        if col == "#1":
            self._toggle_check(idx)

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        idx = int(item)
        if idx >= len(self.songs):
            return

        menu = tk.Menu(self.root, tearoff=0,
                       bg=CLR["surface"], fg=CLR["text"],
                       activebackground=CLR["accent"], activeforeground="#000000",
                       font=FONT["body"])
        menu.add_command(label="🎵 试听",
                         command=lambda: self._preview_single(idx))
        menu.add_command(label="☑ 勾选/取消",
                         command=lambda: self._toggle_check(idx))
        menu.add_command(label="⬇ 下载这首",
                         command=lambda: self._download_one(idx))
        menu.post(event.x_root, event.y_root)

    def _toggle_check(self, idx):
        song = self.songs[idx]
        song.checked = not song.checked
        tag = "☑" if song.checked else "  "
        self.tree.set(str(idx), "sel", tag)

    def _toggle_select_all(self):
        if not self.songs:
            return
        all_checked = all(s.checked for s in self.songs)
        new_state = not all_checked
        for i, s in enumerate(self.songs):
            s.checked = new_state
            self.tree.set(str(i), "sel", "☑" if new_state else "  ")
        self.select_all_btn.configure(text="☐ 取消全选" if new_state else "☑ 全选")

    def _invert_selection(self):
        for i, s in enumerate(self.songs):
            s.checked = not s.checked
            self.tree.set(str(i), "sel", "☑" if s.checked else "  ")

    def _get_checked(self):
        return [i for i, s in enumerate(self.songs) if s.checked]

    # ── 试听 ───────────────────────────────────────────────

    def _preview_selected(self):
        """试听：下载选中歌曲，自动在播放器播放"""
        selected = self._get_checked()
        if not selected:
            sel_items = self.tree.selection()
            selected = [int(i) for i in sel_items if int(i) < len(self.songs)]
        if not selected:
            self._set_status("请先勾选或选中歌曲", "warning")
            return
        if self.downloading:
            self._set_status("正在下载中，请等待当前任务完成", "warning")
            return

        self._preview_mode = True
        self._set_status(f"试听模式：下载 {len(selected)} 首并自动播放...")
        self._start_downloads(selected)

    def _preview_single(self, idx):
        """右键菜单试听：下载单曲并自动播放"""
        if self.downloading:
            self._set_status("正在下载中，请等待当前任务完成", "warning")
            return
        self._preview_mode = True
        self._set_status(f"试听模式：下载 {self.songs[idx].data['name']} 并自动播放...")
        self._start_downloads([idx])

    # ── 下载 ───────────────────────────────────────────────

    def _download_one(self, idx):
        if self.downloading:
            self._set_status("正在下载中，请等待当前任务完成", "warning")
            return
        self._start_downloads([idx])

    def _download_selected(self):
        selected = self._get_checked()
        if not selected:
            sel_items = self.tree.selection()
            selected = [int(i) for i in sel_items if int(i) < len(self.songs)]
        if not selected:
            self._set_status("请先勾选或选中要下载的歌曲", "warning")
            return
        if self.downloading:
            self._set_status("正在下载中，请等待当前任务完成", "warning")
            return
        self._start_downloads(selected)

    def _start_downloads(self, indices):
        self.downloading = True
        self.download_btn.configure(state="disabled", text="下载中...")
        self.dl_widgets.clear()

        # clear progress panel (height auto-fits via _add_progress_widget)
        for w in self.progress_inner.winfo_children():
            w.destroy()
        self._fit_progress_canvas()
        # NOTE: 不再 re-pack —— pack 会把控件移到打包队列末尾，反而让进度面板优先级降到最低；布局已在 _build_search_tab 中固定为 side=BOTTOM。

        self._set_status(f"下载 {len(indices)} 首...")

        # 复制歌曲数据快照，避免后台线程访问 self.songs 的竞态条件
        songs_snapshot = []
        for idx in indices:
            d = self.songs[idx].data
            name = d["name"]
            artists = d.get("artists", "")
            query = d.get("search_query", f"{name} {artists}")
            songs_snapshot.append({
                "name": name,
                "artists": artists,
                "query": query,
                "id": d.get("id"),
                "fee": d.get("fee", 0),
                "download_url": d.get("download_url"),
            })

        thread = threading.Thread(
            target=self._download_worker, args=(songs_snapshot,), daemon=True)
        thread.start()

    def _download_worker(self, songs_snapshot):
        """后台下载线程 — 只读 songs_snapshot，不访问 self.songs"""
        cfg = self.cfg.get_full_config()

        for song in songs_snapshot:
            name = song["name"]
            artists = song.get("artists", "")
            query = song["query"]

            # 创建进度 widget
            self.root.after(0, self._add_progress_widget, name, artists)

            # 0. 优先尝试网易云直链（免费歌曲，无需代理）
            if (cfg.get("netease_direct", True)
                    and song.get("fee", 0) == 0
                    and song.get("id")):
                self.download_queue.put(("status", name, "网易云直链中..."))

                def _netease_progress(pct, spd, _n=name):
                    self.download_queue.put(
                        ("progress", _n, max(pct, 0), spd))

                ok, err = download_netease(
                    song, cfg, progress_callback=_netease_progress)
                if ok:
                    self.download_queue.put(("done", name, "ok", ""))
                    continue
                # 直链失败 → 回退 yt-dlp 音源

            # 1. 搜索
            self.download_queue.put(("status", name, "搜索中..."))
            results = search_multi(query, cfg)

            if not results:
                self.download_queue.put(("done", name, "fail", "未找到资源"))
                continue

            # 2. 下载（取最佳匹配）
            self.download_queue.put(("status", name, "下载中..."))
            ok, err_msg = self._download_single(results[0], cfg, name)

            if ok:
                self.download_queue.put(("done", name, "ok", ""))
            else:
                self.download_queue.put(("done", name, "fail", err_msg or "下载失败"))

        self.download_queue.put(("all_done", "", "", ""))

    def _download_single(self, result, cfg, song_name):
        """执行单个歌曲的下载，返回 (ok: bool, error_msg: str)
        复用 mget._build_dl_opts 构建选项，GUI 只负责进度 hook + 重试策略"""
        import yt_dlp

        src = result.get("source", "youtube")
        last_error = "未知错误"

        def _make_opts(cookies_browser=None, extractor_args=None):
            """基于 mget 的统一选项构建，附加 GUI 进度 hook"""
            opts = _build_dl_opts(cfg, src, cookies_browser, extractor_args)
            opts["quiet"] = True
            opts["no_warnings"] = True
            opts["progress_hooks"] = [self._make_progress_hook(song_name)]
            return opts

        # ── YouTube: 先无 cookies 尝试，失败再用 cookies 回退 ──
        if src == "youtube":
            for strat in YT_STRATEGIES:
                opts = _make_opts(extractor_args=strat)
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([result["url"]])
                    return True, ""
                except Exception as e:
                    last_error = translate_error(e)
                    continue

            for browser in BROWSER_FALLBACK:
                for strat in YT_STRATEGIES:
                    opts = _make_opts(cookies_browser=browser, extractor_args=strat)
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            ydl.download([result["url"]])
                        return True, ""
                    except Exception as e:
                        last_error = translate_error(e)
                        continue

            return False, last_error

        # ── 其他音源: 直接下载 ──
        else:
            try:
                opts = _make_opts()
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([result["url"]])
                return True, ""
            except Exception as e:
                last_error = translate_error(e)
                return False, last_error

    def _make_progress_hook(self, song_name):
        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 1
                downloaded = d.get("downloaded_bytes", 0)
                pct = min(int(downloaded / total * 100), 99)
                speed = d.get("speed") or 0
                speed_str = self._fmt_speed(speed)
                self.download_queue.put(("progress", song_name, pct, speed_str))
            elif d["status"] == "finished":
                self.download_queue.put(("progress", song_name, 100, ""))
        return hook

    def _fmt_speed(self, speed):
        if speed > 1024 * 1024:
            return f"{speed / 1024 / 1024:.1f} MB/s"
        elif speed > 1024:
            return f"{speed / 1024:.0f} KB/s"
        return f"{speed:.0f} B/s"

    def _fit_progress_canvas(self):
        """Auto-fit progress canvas height: collapse when empty, grow up to ~2 rows."""
        self.progress_inner.update_idletasks()
        req = self.progress_inner.winfo_reqheight()
        self.progress_canvas.configure(height=min(req, 150))

    def _add_progress_widget(self, name, artists):
        frame = ttk.Frame(self.progress_inner)
        frame.pack(fill=tk.X, padx=4, pady=3)

        label_text = f"{name} — {artists}" if artists else name
        if len(label_text) > 40:
            label_text = label_text[:38] + "..."

        label = ttk.Label(frame, text=label_text, font=FONT["body"],
                          background=CLR["bg"])
        label.pack(anchor=tk.W)

        pb = ttk.Progressbar(frame, mode="determinate", length=400)
        pb.pack(fill=tk.X, pady=(2, 0))

        status_lbl = ttk.Label(frame, text="等待中...", font=FONT["small"],
                               foreground=CLR["text2"], background=CLR["bg"])
        status_lbl.pack(anchor=tk.W)

        self.dl_widgets[name] = {
            "frame": frame, "pb": pb, "label": label, "status": status_lbl
        }
        self._fit_progress_canvas()

    def _poll_download(self):
        """定时从队列取消息更新 UI（活跃 200ms / 空闲 1000ms 自适应）"""
        had_messages = False
        try:
            while True:
                msg = self.download_queue.get_nowait()
                had_messages = True
                typ = msg[0]
                name = msg[1]

                if typ == "progress":
                    pct = msg[2]
                    speed = msg[3]
                    if name in self.dl_widgets:
                        w = self.dl_widgets[name]
                        w["pb"]["value"] = pct
                        w["status"].configure(
                            text=f"{pct}%  {speed}" if speed else f"{pct}%")

                elif typ == "status":
                    status = msg[2]
                    if name in self.dl_widgets:
                        self.dl_widgets[name]["status"].configure(text=status)

                elif typ == "done":
                    result = msg[2]
                    if name in self.dl_widgets:
                        w = self.dl_widgets[name]
                        if result == "ok":
                            w["pb"]["value"] = 100
                            w["status"].configure(text="✓ 完成", foreground=CLR["success"])
                            w["label"].configure(foreground=CLR["success"])
                            # 下载成功 → 自动加入播放列表
                            prev_count = len(self.player.playlist) if self._preview_mode else 0
                            self._scan_and_add_to_playlist()
                            # 试听模式：自动播放刚下载的第一首歌
                            if self._preview_mode and len(self.player.playlist) > prev_count:
                                self._stop_streamer()  # 试听起播 → 停在线流播，防重叠
                                self.player.play_index(len(self.player.playlist) - 1)
                                self._player_play_btn.configure(text="⏸")
                                self._update_player_bar_state()
                                self._refresh_playlist_display()
                                self._preview_mode = False  # 只自动播第一首
                        else:
                            reason = msg[3]
                            w["status"].configure(text=f"✗ {reason}", foreground=CLR["danger"])
                            w["label"].configure(foreground=CLR["danger"])

                elif typ == "all_done":
                    self.downloading = False
                    self.download_btn.configure(state="normal", text="⬇ 下载选中")
                    ok_count = sum(
                        1 for w in self.dl_widgets.values()
                        if w["pb"]["value"] >= 100
                    )
                    mode_suffix = " | 试听模式" if self._preview_mode else ""
                    self._set_status(
                        f"下载完成: {ok_count}/{len(self.dl_widgets)} 首成功{mode_suffix} | "
                        f"目录: {self.cfg.data['output_dir']}")
                    self._refresh_playlist_display()
                    # 更新流标签页状态
                    if ok_count > 0:
                        self.stream_status_var.set(
                            f"下载完成 ✓ — 可切换到「播放列表」或底部播放器播放")
                    else:
                        self.stream_status_var.set("下载失败 ✗ — 请检查网络或代理设置")
                    self._preview_mode = False

        except queue.Empty:
            pass

        # 自适应轮询：下载中或有消息时 200ms，空闲降到 1000ms 省 CPU
        interval = 200 if (self.downloading or had_messages) else 1000
        self.root.after(interval, self._poll_download)

    # ── 设置操作 ───────────────────────────────────────────

    def _browse_dir(self):
        path = filedialog.askdirectory(title="选择下载目录")
        if path:
            self.dl_dir_var.set(path)

    def _open_output_dir(self):
        """用系统文件管理器打开下载目录"""
        out_dir = os.path.expanduser(self.cfg.data.get("output_dir", "~/Music/mget"))
        os.makedirs(out_dir, exist_ok=True)
        try:
            os.startfile(out_dir)
        except Exception as e:
            self._set_status(f"无法打开文件夹: {e}", "error")

    def _detect_proxy(self):
        """后台检测代理 — 端口扫描+验证最长可达 ~11s，不能阻塞主线程"""
        if self._proxy_detecting:
            return
        self._proxy_detecting = True
        self._set_status("正在检测代理...")

        def worker():
            detected = find_best_proxy()
            ok = bool(detected) and _validate_proxy(detected["url"])
            self.root.after(0, self._on_proxy_detected, detected, ok)

        threading.Thread(target=worker, daemon=True).start()

    def _on_proxy_detected(self, detected, ok):
        self._proxy_detecting = False
        if not detected:
            self._set_status("未检测到代理端口", "warning")
        elif ok:
            self.proxy_var.set(detected["url"])
            self._set_status(f"检测到代理: {detected['name']} ({detected['url']}) ✓")
        else:
            self.proxy_var.set("")
            self._set_status(f"端口开放但代理不可用: {detected['name']}（{detected['url']}）", "warning")

    def _save_settings(self):
        self.cfg.data["output_dir"] = self.dl_dir_var.get()
        self.cfg.data["audio_format"] = self.fmt_var.get()

        qual = self.quality_var.get()
        if qual == "最高":
            self.cfg.data["audio_quality"] = 0
        elif "k" in qual:
            self.cfg.data["audio_quality"] = qual.replace("k", "")

        self.cfg.data["embed_metadata"] = self.embed_meta_var.get()
        self.cfg.data["embed_thumbnail"] = self.embed_thumb_var.get()
        self.cfg.data["search_count"] = int(self.count_var.get())

        proxy_val = self.proxy_var.get()
        if proxy_val == "__auto__" or proxy_val == "":
            self.cfg.data["proxy"] = None
        else:
            self.cfg.data["proxy"] = proxy_val

        # 音源优先级
        priority = []
        for src in ["youtube", "soundcloud", "bilibili"]:
            if self.src_vars[src].get():
                priority.append(src)
        self.cfg.data["source_priority"] = priority
        self.cfg.data["netease_direct"] = self.netease_direct_var.get()
        # 播放模式持久化
        self.cfg.data["player_mode"] = self.player.mode
        self.cfg.data["stream_mode"] = self._stream_mode

        self.cfg.save()
        self.dir_var.set(f"下载目录: {os.path.expanduser(self.cfg.data['output_dir'])}")
        self._set_status("设置已保存 ✓")

    def _reset_settings(self):
        self.dl_dir_var.set(os.path.expanduser("~/Music/mget"))
        self.fmt_var.set("mp3")
        self.quality_var.set("最高")
        self.count_var.set("20")
        self.embed_meta_var.set(True)
        self.embed_thumb_var.set(True)
        self.proxy_var.set("__auto__")
        for src in ["youtube", "soundcloud", "bilibili"]:
            self.src_vars[src].set(True)
        self.netease_direct_var.set(True)
        self._set_status("已恢复默认设置，点击「保存设置」生效")

    # ── 搜索框占位符 ───────────────────────────────────────

    def _on_search_focus_in(self, event):
        pass  # 简单处理，不实现占位符避免复杂

    def _on_search_focus_out(self, event):
        pass

    # ── 状态栏 ─────────────────────────────────────────────

    def _set_status(self, text, level="info"):
        self.status_var.set(text)
        if level == "warning":
            self.status_lbl.configure(foreground=CLR["warning"])
        elif level == "error":
            self.status_lbl.configure(foreground=CLR["danger"])
        else:
            self.status_lbl.configure(foreground=CLR["text2"])


# ════════════════════════════════════════════════════════════
#  入口
# ════════════════════════════════════════════════════════════

_mutex_handle = None

def _check_single_instance():
    """Windows 单实例锁。若已有实例在运行则返回 True。"""
    global _mutex_handle
    if sys.platform != "win32":
        return False
    import ctypes
    kernel32 = ctypes.windll.kernel32
    _mutex_handle = kernel32.CreateMutexW(None, False, "PitayaMusicSingleInstance")
    return kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

def main():
    if _check_single_instance():
        import tkinter.messagebox as mb
        mb.showwarning("Pitaya Music", "程序已在运行，请勿重复打开。")
        return
    try:
        root = tk.Tk()
        app = MgetApp(root)
        root.mainloop()
    except Exception:
        import traceback
        log_path = Path(__file__).parent / "error.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("mget GUI 启动失败\n")
            f.write("=" * 40 + "\n")
            traceback.print_exc(file=f)
        # 尽量弹窗告知用户
        try:
            import tkinter.messagebox as mb
            mb.showerror("启动失败",
                f"程序启动时出现错误，详情已写入:\n{log_path}")
        except Exception:
            pass


if __name__ == "__main__":
    main()