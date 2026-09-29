#!/usr/bin/env python3
"""
mget 启动器 — 交互式命令行界面
绕过 Windows CMD 编码问题，纯 Python 实现
"""

import sys
import os

# 确保 mget.py 的函数可用
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mget import load_config, search_multi as search, display_results, download


def main():
    # 切换到脚本所在目录
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print()
    print("=" * 40)
    print("     音乐下载器 mget")
    print("=" * 40)
    print()
    print("输入歌名（可选加歌手），q 退出")
    print("示例: 后来 刘若英")
    print("      海阔天空 Beyond")
    print("-" * 40)
    print()

    # 配置只加载一次（内含代理检测验证，避免每次搜歌重复等待数秒）
    cfg = load_config()

    while True:
        try:
            keyword = input("搜歌: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        if not keyword:
            continue
        if keyword.lower() == "q":
            print("\n再见!")
            break

        print()

        # 直接调用 mget.py 的函数
        results = search(keyword, cfg)
        if not results:
            print()
            print("-" * 40)
            print()
            continue

        display_results(results, keyword)

        # 用户选择
        while True:
            try:
                choice = input("\n选择 (1-%d), 或 q 退出: " % len(results)).strip()
                if choice.lower() == "q":
                    print("\n再见!")
                    sys.exit(0)
                idx = int(choice)
                if 1 <= idx <= len(results):
                    break
                print("请输入 1-%d 之间的数字" % len(results))
            except ValueError:
                print("请输入数字")

        download(results[idx - 1], cfg)

        print()
        print("-" * 40)
        print()


if __name__ == "__main__":
    main()
