"""Capture dashboard screenshots for the PPT via headless Chrome (DevTools protocol).

Usage: uv run python scripts/screenshots.py [--url http://127.0.0.1:8765] [--theme dark|light]
Needs the API running (`uv run aurora serve`) and Google Chrome installed.
"""
import argparse
import asyncio
import base64
import json
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
TABS = ["overview", "forecast", "decisions", "fuel", "lab"]


async def shoot(url: str, theme: str, width: int, height: int, wait_s: float):
    port = 9333
    profile = tempfile.mkdtemp(prefix="aurora-shot-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--hide-scrollbars", f"--window-size={width},{height}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=50_000_000) as ws:
            n = 0

            async def cmd(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == n:
                        return m.get("result", {})

            await cmd("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2, mobile=False)
            OUT.mkdir(parents=True, exist_ok=True)
            for tab in TABS:
                await cmd("Page.navigate", url=f"{url}/?t={time.time()}#{tab}")
                await asyncio.sleep(1.0)
                await cmd("Runtime.evaluate", expression=f"localStorage.setItem('aurora-theme','{theme}'); document.documentElement.dataset.theme='{theme}'")
                await cmd("Page.reload")
                await asyncio.sleep(wait_s)
                h = (await cmd("Runtime.evaluate", expression="document.documentElement.scrollHeight", returnByValue=True))["result"]["value"]
                await cmd("Emulation.setDeviceMetricsOverride", width=width, height=int(h), deviceScaleFactor=2, mobile=False)
                await asyncio.sleep(1.0)
                shot = await cmd("Page.captureScreenshot", format="png", captureBeyondViewport=True)
                path = OUT / f"{tab}_{theme}.png"
                path.write_bytes(base64.b64decode(shot["data"]))
                print(path)
                await cmd("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2, mobile=False)
    finally:
        proc.terminate()


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--url", default="http://127.0.0.1:8765")
    a.add_argument("--theme", default="dark")
    a.add_argument("--width", type=int, default=1440)
    a.add_argument("--height", type=int, default=900)
    a.add_argument("--wait", type=float, default=5.0)
    args = a.parse_args()
    asyncio.run(shoot(args.url, args.theme, args.width, args.height, args.wait))
