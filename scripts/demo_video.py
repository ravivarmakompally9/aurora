"""Record a 2-3 minute demo video of the dashboard via headless Chrome (DevTools protocol) and ffmpeg.

Usage: uv run --with imageio-ffmpeg python scripts/demo_video.py [--url http://127.0.0.1:8767]
Needs the API running (`uv run aurora serve --port 8767`) and Google Chrome installed.
Writes demo_video/aurora_demo.mp4 and demo_video/timeline.json (scene start times for the voiceover).
Uses the demo presets, so it resets the station it records: point it at a server you are not using.
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

import imageio_ffmpeg
import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = Path(__file__).resolve().parent.parent / "demo_video"
W, H, FPS = 1920, 1080, 30

# Page-side helpers: eased scrolling, a visible cursor that clicks, captions and full-screen cards.
HELPERS = r"""
window.__demo = (() => {
  const ease = (t) => t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
  const css = document.createElement('style');
  css.textContent = `
    #demo-cursor{position:fixed;z-index:99998;width:26px;height:26px;margin:-13px 0 0 -13px;border-radius:50%;
      background:rgba(13,148,136,.25);border:2.5px solid #0d9488;pointer-events:none;left:1500px;top:900px;
      transition:left .9s cubic-bezier(.65,0,.35,1),top .9s cubic-bezier(.65,0,.35,1),transform .15s;opacity:0}
    #demo-cursor.press{transform:scale(.7)}
    .demo-ripple{position:fixed;z-index:99997;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;
      border:3px solid #0d9488;pointer-events:none;animation:demo-rip .7s ease-out forwards}
    @keyframes demo-rip{to{transform:scale(4);opacity:0}}
    #demo-cap{position:fixed;z-index:99996;left:32px;bottom:32px;padding:14px 22px;border-radius:14px;
      background:rgba(15,23,42,.92);color:#fff;font:600 22px var(--font);box-shadow:0 10px 30px rgba(0,0,0,.25);
      transition:opacity .5s, transform .5s;opacity:0;transform:translateY(12px);max-width:760px}
    #demo-cap small{display:block;font-weight:500;font-size:16px;color:#99f6e4;margin-top:3px}
    #demo-cap.on{opacity:1;transform:none}
    #demo-card{position:fixed;inset:0;z-index:99999;display:flex;flex-direction:column;justify-content:center;
      padding:0 160px;color:#e2e8f0;font-family:var(--font);transition:opacity .7s;opacity:0;pointer-events:none;
      background:radial-gradient(1200px 500px at 75% -10%,rgba(45,212,191,.35),transparent 60%),
                 radial-gradient(900px 400px at 10% 0%,rgba(129,140,248,.30),transparent 60%),
                 linear-gradient(180deg,#0b1224,#060a16)}
    #demo-card.on{opacity:1}
    #demo-card .k{font:700 24px var(--font);letter-spacing:.18em;text-transform:uppercase;color:#5eead4}
    #demo-card h1{font:800 132px/1.02 var(--font);margin:18px 0 0;color:#fff;letter-spacing:-.02em}
    #demo-card h2{font:700 68px/1.1 var(--font);margin:18px 0 0;color:#fff;letter-spacing:-.01em}
    #demo-card p{font:500 34px/1.45 var(--font);margin:28px 0 0;color:#cbd5e1;max-width:1400px}
    #demo-card .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:22px;margin-top:48px}
    #demo-card .tile{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:28px}
    #demo-card .tile b{display:block;font:800 60px var(--font);color:#5eead4;letter-spacing:-.02em}
    #demo-card .tile span{font:500 22px/1.35 var(--font);color:#cbd5e1}
    #demo-card .foot{position:absolute;left:160px;bottom:56px;font:500 18px var(--font);color:#64748b}
    #demo-card ul{margin:34px 0 0;padding:0;list-style:none;font:500 36px/1.5 var(--font);color:#cbd5e1}
    #demo-card li{margin:10px 0;padding-left:44px;position:relative}
    #demo-card li:before{content:'';position:absolute;left:0;top:24px;width:22px;height:4px;border-radius:2px;background:#5eead4}`;
  document.head.appendChild(css);
  const cur = document.createElement('div'); cur.id = 'demo-cursor'; document.body.appendChild(cur);
  const cap = document.createElement('div'); cap.id = 'demo-cap'; document.body.appendChild(cap);
  const card = document.createElement('div'); card.id = 'demo-card'; document.body.appendChild(card);
  const find = (text, sel = 'button, a, .nav-item') =>
    [...document.querySelectorAll(sel)].find((e) => e.offsetParent && e.textContent.trim().includes(text));
  const scrollTo = (y, ms = 1500) => {
    const y0 = window.scrollY, max = document.documentElement.scrollHeight - innerHeight;
    const y1 = Math.max(0, Math.min(max, y)), t0 = performance.now();
    const step = (now) => { const t = Math.min(1, (now - t0) / ms); window.scrollTo(0, y0 + (y1 - y0) * ease(t)); if (t < 1) requestAnimationFrame(step) };
    requestAnimationFrame(step);
  };
  return {
    scrollTo,
    scrollBy: (dy, ms) => scrollTo(window.scrollY + dy, ms),
    scrollToText: (text, ms = 1500, off = 120) => {
      const el = [...document.querySelectorAll('h1,h2,h3,h4,b,span,div,p')].find((e) => e.children.length === 0 && e.textContent.trim().startsWith(text) && e.offsetParent);
      if (el) scrollTo(el.getBoundingClientRect().top + window.scrollY - off, ms);
      return !!el;
    },
    scrollEnd: (ms = 2000) => scrollTo(1e9, ms),
    click: (text, sel) => {
      const el = find(text, sel); if (!el) return false;
      el.scrollIntoView({ block: 'nearest' });
      const r = el.getBoundingClientRect(); cur.style.opacity = 1;
      cur.style.left = (r.left + r.width / 2) + 'px'; cur.style.top = (r.top + r.height / 2) + 'px';
      setTimeout(() => {
        cur.classList.add('press');
        const rp = document.createElement('div'); rp.className = 'demo-ripple';
        rp.style.left = cur.style.left; rp.style.top = cur.style.top; document.body.appendChild(rp);
        setTimeout(() => rp.remove(), 800);
        setTimeout(() => { cur.classList.remove('press'); el.click() }, 160);
      }, 1000);
      return true;
    },
    clickSel: (sel) => {
      const el = [...document.querySelectorAll(sel)].find((e) => e.offsetParent); if (!el) return false;
      const r = el.getBoundingClientRect(); cur.style.opacity = 1;
      cur.style.left = (r.left + r.width / 2) + 'px'; cur.style.top = (r.top + r.height / 2) + 'px';
      setTimeout(() => { cur.classList.add('press'); setTimeout(() => { cur.classList.remove('press'); el.click() }, 160) }, 1000);
      return true;
    },
    hideCursor: () => { cur.style.opacity = 0 },
    caption: (t, s) => { cap.innerHTML = t + (s ? `<small>${s}</small>` : ''); cap.classList.add('on') },
    uncaption: () => cap.classList.remove('on'),
    card: (html) => { card.innerHTML = html; card.classList.add('on') },
    uncard: () => card.classList.remove('on'),
  };
})();
"""


class Chrome:
    def __init__(self, ws):
        self.ws, self.n, self.pending = ws, 0, {}
        self.reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            m = json.loads(raw)
            if "id" in m and m["id"] in self.pending:
                self.pending.pop(m["id"]).set_result(m.get("result", {}))

    async def cmd(self, method, **params):
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        return await fut

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        return r.get("result", {}).get("value")


class Recorder:
    """Captures screenshots and writes them to ffmpeg at a constant 30 fps, duplicating frames as needed."""

    def __init__(self, chrome: Chrome, path: Path):
        self.c, self.frames, self.last = chrome, 0, None
        self.ff = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe",
                                    "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium",
                                    "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
        self.marks = []

    @property
    def t(self):
        return self.frames / FPS

    def mark(self, scene):
        self.marks.append({"scene": scene, "start_s": round(self.t, 1)})
        print(f"{self.t:6.1f}s  {scene}")

    async def hold(self, seconds: float, speedup: float = 1.0):
        """Record `seconds` of video; with speedup > 1, real time runs faster than video time (time-lapse)."""
        target = self.frames + round(seconds * FPS)
        t0, f0 = time.monotonic(), self.frames
        while self.frames < target:
            shot = await self.c.cmd("Page.captureScreenshot", format="jpeg", quality=92)
            self.last = base64.b64decode(shot["data"])
            due = min(target, f0 + int((time.monotonic() - t0) / speedup * FPS) + 1)
            while self.frames < due:
                self.ff.stdin.write(self.last)
                self.frames += 1

    def close(self):
        self.ff.stdin.close()
        self.ff.wait()


def card_intro():
    return ("<div class='k'>Smart India Hackathon · PS 26061 · MoES / NCPOR</div><h1>AURORA</h1>"
            "<p>An offline AI energy manager for India's polar research stations: it forecasts, plans and guards "
            "power, heat and fuel, every 15 minutes.</p><div class='foot'>Prototype on a digital twin of Bharati Station, "
            "Antarctica · all figures simulated</div>")


def card_problem():
    return ("<div class='k'>The problem</div><h2>Diesel, shipped once a year,<br>to the bottom of the world</h2>"
            "<ul><li>Generators run on fixed rules, often half-loaded, wasting fuel</li>"
            "<li>Sun and wind are curtailed when no one plans around them</li>"
            "<li>A blizzard or a late ship can put the whole station at risk</li></ul>")


def card_results():
    return ("<div class='k'>One full simulated year · Bharati · 2023 NASA POWER weather</div>"
            "<h2>AURORA against today's diesel-first rules</h2><div class='grid'>"
            "<div class='tile'><b>−22.5%</b><span>diesel<br>62,000 L saved</span></div>"
            "<div class='tile'><b>166 t</b><span>CO₂ avoided<br>in one year</span></div>"
            "<div class='tile'><b>100%</b><span>life-support load<br>served, always</span></div>"
            "<div class='tile'><b>+84</b><span>reserve days of fuel<br>at resupply</span></div></div>"
            "<p style='font-size:24px'>Generator run-hours −67% · curtailment 24.7% → 0% · 2,920 plans, 1.2 s each, zero failures</p>")


def card_outro():
    return ("<div class='k'>AURORA</div><h2>Sense → predict → decide → guard → act</h2>"
            "<p>Runs fully offline on a station computer. Forecasts with uncertainty, plans with an optimiser, "
            "explains every decision and never cuts life support.</p>"
            "<p style='font-size:24px;color:#5eead4'>Demo: ravivarmakompally9.github.io/aurora</p>"
            "<div class='foot'>SIH PS 26061 · all figures from the digital twin, not a real station</div>")


async def record(url: str):
    port = 9334
    profile = tempfile.mkdtemp(prefix="aurora-video-")
    proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--hide-scrollbars", f"--window-size={W},{H}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    OUT.mkdir(parents=True, exist_ok=True)

    def api(path, body):
        req = urllib.request.Request(f"{url}{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=300))

    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page")
        async with websockets.connect(ws_url, max_size=100_000_000) as ws:
            c = Chrome(ws)
            await c.cmd("Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=False)
            api("/api/sim/preset", {"name": "reset"})
            api("/api/sim/control", {"action": "pause"})
            await c.cmd("Page.navigate", url=f"{url}/#overview")
            await asyncio.sleep(1.0)
            await c.js("localStorage.setItem('aurora-seen-help','1'); localStorage.setItem('aurora-tour-hidden','true')")
            await c.cmd("Page.navigate", url=f"{url}/?v={time.time()}#overview")
            await asyncio.sleep(5.0)
            await c.js(HELPERS)
            d = "window.__demo"

            async def go(tab):  # sidebar navigation with the visible cursor
                labels = {"overview": "Station now", "forecast": "Next 48 hours", "decisions": "Why AURORA acted",
                          "fuel": "Will fuel last?", "lab": "Try scenarios"}
                await c.js(f"{d}.click({json.dumps(labels[tab])}, '.nav-item')")

            async def wait_tab(tab, settle=4.0):
                for _ in range(600):
                    if await c.js(f"location.hash === '#{tab}' && !document.querySelector('[aria-busy=\"true\"]')"):
                        break
                    await asyncio.sleep(0.2)
                await asyncio.sleep(settle)

            async def loaded(timeout=90):
                busy = "['Waiting for the first forecast', 'Loading decisions', 'Planning…', 'Loading']"
                for _ in range(int(timeout / 0.25)):
                    if await c.js(f"!{busy}.some((t) => document.querySelector('main, #root').innerText.includes(t))"):
                        return
                    await asyncio.sleep(0.25)

            async def close_impact():
                await c.js(f"{d}.clickSel('[aria-label=\"Close event impact\"]')")

            rec = Recorder(c, OUT / "aurora_demo.mp4")

            # 1-2. Title and problem
            await c.js(f"{d}.card({json.dumps(card_intro())})")
            await asyncio.sleep(1.0)
            rec.mark("1. Intro")
            await rec.hold(9)
            await c.js(f"{d}.card({json.dumps(card_problem())})")
            rec.mark("2. Problem")
            await rec.hold(11)

            # 3. Station now
            api("/api/sim/control", {"action": "play"})
            await c.js(f"{d}.uncard(); {d}.caption('Station now', 'Live digital twin of Bharati Station')")
            rec.mark("3. Station now")
            await rec.hold(5)
            await c.js(f"{d}.scrollToText('Where the power is going', 2200)")
            await rec.hold(7)
            await c.js(f"{d}.scrollToText('What AURORA is doing', 2200)")
            await rec.hold(6)
            await c.js(f"{d}.scrollEnd(2000)")
            await rec.hold(4)

            # 4. Next 48 hours
            await c.js(f"{d}.scrollTo(0, 900)")
            api("/api/sim/control", {"action": "pause"})
            urllib.request.urlopen(f"{url}/api/forecast", timeout=120).read()
            await go("forecast")
            await rec.hold(1.2)
            await loaded()
            await c.js(f"{d}.caption('Next 48 hours', 'Forecasts with P10–P90 bands → an optimised plan')")
            rec.mark("4. Next 48 hours")
            await rec.hold(5)
            await c.js(f"{d}.scrollBy(560, 2400)")
            await rec.hold(5)
            await c.js(f"{d}.scrollBy(620, 2400)")
            await rec.hold(4.5)
            await c.js(f"{d}.scrollEnd(2400)")
            await rec.hold(3.5)

            # 5. Blizzard demo
            await c.js(f"{d}.scrollTo(0, 900)")
            await go("lab")
            await c.js(f"{d}.caption('Scenario: blizzard incoming', 'Winds rise in 16 h · 1 simulated hour per second')")
            rec.mark("5. Blizzard demo")
            await rec.hold(2.2)
            await c.js(f"{d}.click('Blizzard demo')")
            await rec.hold(2.0)
            await wait_tab("forecast")
            await c.js(f"{d}.hideCursor()")
            await rec.hold(3.5)
            await close_impact()
            await rec.hold(2.5)
            await go("overview")
            await rec.hold(2)
            await close_impact()
            await rec.hold(1.5)
            await c.js(f"{d}.caption('Storm Mode', 'Pre-charge battery, pre-heat tank, standby generator, park turbines')")
            await rec.hold(4)
            await c.js(f"{d}.scrollToText('Where the power is going', 2000)")
            await rec.hold(3)

            # 6. Why AURORA acted
            await c.js(f"{d}.scrollTo(0, 800)")
            api("/api/sim/control", {"action": "pause"})
            urllib.request.urlopen(f"{url}/api/decisions", timeout=120).read()
            await go("decisions")
            await rec.hold(1.2)
            await loaded()
            await c.js(f"{d}.caption('Why AURORA acted', 'Every decision comes with a plain-language reason')")
            rec.mark("6. Why AURORA acted")
            await rec.hold(5)
            await c.js(f"{d}.scrollBy(600, 2600)")
            await rec.hold(7)

            # 7. Generator failure, during the storm so a unit is actually running
            api("/api/sim/control", {"action": "play"})
            await c.js(f"{d}.scrollTo(0, 800)")
            await go("lab")
            await c.js(f"{d}.caption('Scenario: generator failure', 'G1 trips mid-storm · AURORA re-plans with one fewer unit')")
            rec.mark("7. Generator failure")
            await rec.hold(2.2)
            await c.js(f"{d}.click('Generator failure')")
            await rec.hold(2.0)
            await wait_tab("overview", settle=3.0)
            await c.js(f"{d}.hideCursor()")
            await rec.hold(6)
            await close_impact()
            await rec.hold(1.5)
            await c.js(f"{d}.scrollToText('Where the power is going', 2000)")
            await rec.hold(3)

            # 8. Ship delay
            await c.js(f"{d}.scrollTo(0, 800)")
            await go("lab")
            await c.js(f"{d}.caption('Scenario: ship delayed 30 days', 'Will the fuel last until the ship arrives?')")
            rec.mark("8. Ship delay → Will fuel last?")
            await rec.hold(2.2)
            await c.js(f"{d}.click('Ship-delay demo')")
            await rec.hold(2.0)
            await wait_tab("fuel", settle=5.0)
            await c.js(f"{d}.hideCursor()")
            await rec.hold(3)
            await close_impact()
            await rec.hold(2.5)
            await c.js(f"{d}.scrollBy(560, 2400)")
            await rec.hold(4.5)
            await c.js(f"{d}.scrollBy(620, 2400)")
            await rec.hold(4.5)

            # 9. The year in 60 seconds
            api("/api/sim/control", {"action": "pause"})
            await c.js(f"{d}.scrollTo(0, 800)")
            await go("lab")
            await c.js(f"{d}.caption('A full year: AURORA vs diesel-first', '2023 weather · same twin, loads and events')")
            rec.mark("9. Year comparison")
            await rec.hold(2)
            await c.js(f"{d}.scrollToText('A · The year', 1600) || {d}.scrollBy(520, 1600)")
            await rec.hold(2)
            await c.js(f"{d}.click('Replay year')")
            await rec.hold(10, speedup=4)  # time-lapse of the 60 s replay
            await c.js(f"{d}.click('Skip to end')")
            await rec.hold(2.5)
            await c.js(f"{d}.hideCursor(); {d}.scrollToText('What changed', 2200)")
            await rec.hold(6)

            # 10-11. Results and close
            await c.js(f"{d}.uncaption(); {d}.card({json.dumps(card_results())})")
            rec.mark("10. Results")
            await rec.hold(13)
            await c.js(f"{d}.card({json.dumps(card_outro())})")
            rec.mark("11. Close")
            await rec.hold(9)
            rec.close()
            (OUT / "timeline.json").write_text(json.dumps({"duration_s": round(rec.t, 1), "scenes": rec.marks}, indent=2))
            print(f"done: {OUT / 'aurora_demo.mp4'} ({rec.t:.1f} s)")
            api("/api/sim/preset", {"name": "reset"})
    finally:
        proc.terminate()


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--url", default="http://127.0.0.1:8767")
    asyncio.run(record(a.parse_args().url))
