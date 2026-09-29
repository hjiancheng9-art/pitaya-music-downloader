<div align="center">

# 🍉 Pitaya 音乐下载器

**简洁实用的桌面音乐搜索下载工具（GUI + CLI）**

![Python](https://img.shields.io/badge/Python-3.8+-blue)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/badge/License-MIT-green)

*by 火龙果不是输的*

</div>

---

## ✨ 功能特性

- 🎧 **图形界面** — 搜索、试听、下载、播放列表、内置播放器，一个窗口全搞定
- 🔍 **多音源自动回退** — YouTube → SoundCloud → Bilibili 按优先级依次尝试，失败自动切换下一个
- ⚡ **网易云直链优先** — 免费歌曲走官方直链直接下载 MP3，无需代理；VIP / 版权受限歌曲自动回退其它音源
- 🏷️ **VIP 标记** — 搜索结果直接标注 VIP 歌曲，下载前心中有数
- 🎵 **试听后再下载** — 选择编号前可先试听，避免下错歌
- 🕵️ **自动代理检测** — 自动探测 Clash / V2RayN 等常见本地代理端口，海外音源开箱即用
- 🎚️ **音质可选** — 自动嵌入歌曲元数据与封面图
- 🖥️ **双入口** — 图形界面（`gui.py`）与命令行（`mget.py`）共用同一套核心逻辑

## 🚀 快速开始

### 环境要求

- Python 3.8+
- 播放器功能需要本地安装 [VLC](https://www.videolan.org/)（可选，仅在线试听需要）

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/hjiancheng9-art/pitaya-music-downloader.git
cd pitaya-music-downloader

# 安装依赖
pip install -r requirements.txt

# 启动图形界面
python gui.py

# 或使用命令行模式
python mget.py
```

Windows 用户也可以直接双击 `Pitaya Music.bat`（带控制台）或 `Pitaya Music.vbs`（无控制台）一键启动。

### 打包为 EXE

```bash
pip install pyinstaller
pyinstaller -F -w -i pitaya_icon.ico gui.py
```

## ⚙️ 配置说明（config.yaml）

| 配置项 | 说明 |
|--------|------|
| `output_dir` | 下载目录，默认 `~/Music/mget` |
| `audio_format` | 输出格式，默认 `mp3` |
| `audio_quality` | `0` 为最高音质 |
| `source_priority` | 音源优先级顺序，可自由增删排序 |
| `netease_direct` | 网易云直链优先开关（免费歌免代理直下） |
| `proxy` | 代理地址，留空则自动检测（如 Clash: `http://127.0.0.1:7890`） |

## 📁 项目结构

```
pitaya-music-downloader/
├── gui.py               # 图形界面主程序（Tkinter）
├── mget.py              # 核心逻辑：搜索 / 下载 / 命令行
├── player.py            # 内置播放器引擎
├── streamer.py          # 在线试听 / 流式播放
├── proxy_detector.py    # 本地代理自动检测
├── 启动器.py            # 命令行交互启动器
├── config.yaml          # 配置文件
├── pitaya_icon.ico      # 应用图标
├── Pitaya Music.bat     # Windows 一键启动（带控制台）
├── Pitaya Music.vbs     # Windows 一键启动（无控制台）
├── requirements.txt
└── tests/               # 单元测试
```

## 🧪 运行测试

```bash
python -m pytest tests/ -v
```

## 🗺️ 待办事项

- [ ] 界面截图与演示 GIF
- [ ] 歌词下载与显示
- [ ] 歌单 / 专辑链接解析批量下载
- [ ] 跨平台适配（macOS / Linux）

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 许可证

[MIT](LICENSE) © 火龙果不是输的

> ⚠️ **免责声明**：本项目仅供学习交流使用，请于下载后 24 小时内删除，请支持正版音乐。
