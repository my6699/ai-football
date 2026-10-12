"""最终验证：Understat 直连 / 本地代理 两条路径的可用性。"""
import socket
import time

import httpx

PROXY = "socks5://127.0.0.1:10808"
URL = "https://understat.com/getLeagueData/EPL/2024"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://understat.com/",
}


def probe_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=3):
            return True
    except Exception:
        return False


def try_get(label, proxy):
    t0 = time.time()
    try:
        r = httpx.get(URL, headers=HEADERS, proxy=proxy, timeout=25.0, follow_redirects=True)
        dt = time.time() - t0
        body = r.content
        print(f"[{label}] OK status={r.status_code} bytes={len(body)} {dt:.1f}s")
        return True
    except Exception as e:
        dt = time.time() - t0
        print(f"[{label}] FAIL {type(e).__name__}: {str(e)[:120]} {dt:.1f}s")
        return False


if __name__ == "__main__":
    print("proxy port 10808:", "OPEN" if probe_port("127.0.0.1", 10808) else "CLOSED")
    print("--- google via proxy (sanity) ---")
    try:
        t0 = time.time()
        r = httpx.get("https://www.google.com", proxy=PROXY, timeout=15.0)
        print(f"[google] OK status={r.status_code} {time.time()-t0:.1f}s")
    except Exception as e:
        print(f"[google] FAIL {type(e).__name__}: {str(e)[:120]}")
    print("--- understat direct ---")
    try_get("understat-direct", None)
    print("--- understat via proxy ---")
    try_get("understat-proxy", PROXY)