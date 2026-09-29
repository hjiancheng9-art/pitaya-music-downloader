#!/usr/bin/env python3
"""
代理自动检测器
扫描常见代理软件端口，自动获取可用代理地址
"""

import socket
import subprocess
import sys


# 常见代理软件端口
PROXY_PORTS = {
    "Clash HTTP":    ("http://127.0.0.1:7890", 7890),
    "Clash Socks5":  ("socks5://127.0.0.1:7891", 7891),
    "V2RayN HTTP":   ("http://127.0.0.1:10809", 10809),
    "V2RayN Socks5": ("socks5://127.0.0.1:10808", 10808),
    "SSR":           ("socks5://127.0.0.1:1080", 1080),
    "Clash Verge":   ("http://127.0.0.1:7890", 7890),
}


def is_port_open(host, port, timeout=1):
    """检测端口是否开放"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def detect_proxy():
    """自动检测可用的代理，返回代理 URL 或 None"""
    for name, (url, port) in PROXY_PORTS.items():
        if is_port_open("127.0.0.1", port):
            return {"url": url, "name": name, "port": port}
    return None


def get_system_proxy():
    """尝试从 Windows 注册表读取系统代理"""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
        if proxy_enable and proxy_server:
            # proxy_server 格式可能是 "127.0.0.1:7890" 或 "http=127.0.0.1:7890"
            if "=" in proxy_server:
                proxy_server = proxy_server.split("=")[-1]
            return {"url": f"http://{proxy_server}", "name": "系统代理", "port": int(proxy_server.split(":")[-1])}
    except Exception:
        pass
    return None


def find_best_proxy():
    """找到最佳代理：自动检测 > 系统代理 > None"""
    # 优先检测常见代理软件
    auto = detect_proxy()
    if auto:
        return auto
    # 其次读取系统代理
    system = get_system_proxy()
    if system:
        return system
    return None


if __name__ == "__main__":
    proxy = find_best_proxy()
    if proxy:
        print(f"✅ 找到代理: {proxy['name']} ({proxy['url']})")
    else:
        print("❌ 未检测到可用代理")
