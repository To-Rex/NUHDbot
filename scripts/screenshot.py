"""Headless-Chrome screenshots via CDP with cookies — visual QA without playwright.

usage: uv run python scripts/screenshot.py "<chrome-binary>" <out-dir> <WxH> <cookie-domain> "<name=value;...>" <url> [<url> ...]
example: uv run python scripts/screenshot.py "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" /tmp/shots 1400x900 127.0.0.1 "nuhd_admin=<cookie>" http://127.0.0.1:8000/admin
"""
# ruff: noqa: E701, E702
import asyncio
import base64
import itertools
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

import websockets

chrome, out_dir, size, cookie_domain, cookies, *urls = sys.argv[1:]
W, H = (int(x) for x in size.split("x"))
out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
port = 9333
proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={port}", "--no-first-run", "--no-default-browser-check",
                         "--disable-gpu", "--hide-scrollbars", f"--window-size={W},{H}", "--user-data-dir=/tmp/nuhd-chrome-profile", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version")); break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("chrome did not start")

    async def main():
        ids = itertools.count(1)
        async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=50_000_000) as bws:
            async def call(ws, method, **params):
                i = next(ids); await ws.send(json.dumps({"id": i, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == i:
                        if "error" in msg: raise RuntimeError(msg["error"])
                        return msg.get("result", {})
            t = await call(bws, "Target.createTarget", url="about:blank")
            page_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{t['targetId']}"
            async with websockets.connect(page_ws_url, max_size=50_000_000) as ws:
                await call(ws, "Page.enable"); await call(ws, "Network.enable"); await call(ws, "Runtime.enable")
                await call(ws, "Emulation.setDeviceMetricsOverride", width=W, height=H, deviceScaleFactor=1, mobile=W < 600)
                for c in filter(None, cookies.split(";")):
                    n, v = c.split("=", 1)
                    await call(ws, "Network.setCookie", name=n.strip(), value=v.strip(), domain=cookie_domain, path="/")
                for k, url in enumerate(urls):
                    await call(ws, "Page.navigate", url=url)
                    await asyncio.sleep(2.5)
                    # console errors + layout facts
                    facts = await call(ws, "Runtime.evaluate", returnByValue=True, expression="""(() => {
                      const q = s => document.querySelector(s); const r = el => el ? el.getBoundingClientRect() : null;
                      const b = r(q('body')), sb = r(q('.sidebar')), mn = r(q('.main')), ct = r(q('.content'));
                      const cs = el => el ? getComputedStyle(el) : null; const c = cs(q('.content')), m = cs(q('.main')), sh = cs(q('.shell'));
                      return JSON.stringify({title: document.title, bodyW: b && b.width, sidebar: sb && [sb.x, sb.y, sb.width, sb.height], main: mn && [mn.x, mn.y, mn.width, mn.height],
                        content: ct && [ct.x, ct.y, ct.width, ct.height], contentOpacity: c && c.opacity, contentDisplay: c && c.display, contentColor: c && c.color, bodyBg: cs(document.body).backgroundColor,
                        shellCols: sh && sh.gridTemplateColumns, shellDisplay: sh && sh.display, fontsReady: document.fonts.status, textSample: (q('.content') && q('.content').innerText.slice(0, 80)) });
                    })()""")
                    print(url, "->", facts.get("result", {}).get("value"))
                    shot = await call(ws, "Page.captureScreenshot", format="png", captureBeyondViewport=False)
                    p = out / f"{k:02d}.png"; p.write_bytes(base64.b64decode(shot["data"])); print("saved", p)
    asyncio.run(main())
finally:
    proc.terminate()
