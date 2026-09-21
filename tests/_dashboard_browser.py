"""
tests/_dashboard_browser.py
----------------------------
Minimal Chrome DevTools Protocol driver for real-browser verification of
``dashboard_web_static/index.html``'s refresh behaviour (Task 140). Not a
test module.

No Node.js, Playwright or Selenium is installed in this environment, but
Google Chrome itself IS already installed -- this drives it directly over
its own standard remote-debugging protocol using only packages already in
the project's venv (``websocket-client``, stdlib ``subprocess``/
``urllib``), matching this task's own instruction to use "existing
browser tooling" rather than add a new frontend/test framework.
"""
from __future__ import annotations

import base64
import itertools
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_chrome() -> str | None:
    for c in _CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class CDPPage:
    """One headless Chrome instance (isolated profile) + its single page,
    driven over one raw CDP WebSocket (JSON-RPC by hand -- no client
    library beyond the already-installed ``websocket-client`` transport)."""

    def __init__(self, chrome_path: str, *, headless: bool = True, window=(1280, 1600)):
        self._port = free_port()
        self._profile_dir = tempfile.mkdtemp(prefix="talonx_cdp_profile_")
        args = [chrome_path, f"--remote-debugging-port={self._port}",
                f"--user-data-dir={self._profile_dir}",
                "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                # Recent Chrome rejects a devtools WebSocket connection whose
                # Origin header doesn't match an explicit allowlist -- this
                # local, ephemeral, isolated-profile instance is never
                # reachable from anywhere but this test process.
                "--remote-allow-origins=*",
                f"--window-size={window[0]},{window[1]}", "about:blank"]
        if headless:
            args.insert(1, "--headless=new")
        self._proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._id_counter = itertools.count(1)
        self._ws = self._connect_page()
        self._send("Page.enable")
        self._send("Runtime.enable")

    def _connect_page(self):
        deadline = time.time() + 20
        last_exc: Exception | None = None
        # Recent Chrome versions require PUT (not GET) for /json/new --
        # CSRF hardening of the HTTP side of the devtools endpoint.
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/json/new?about:blank", method="PUT")
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(req, timeout=2) as r:
                    info = json.loads(r.read())
                return websocket.create_connection(info["webSocketDebuggerUrl"], timeout=15)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.3)
        raise RuntimeError(f"could not connect to headless Chrome on port {self._port}: {last_exc}")

    def _send(self, method: str, params: dict | None = None, timeout: float = 20) -> dict:
        cid = next(self._id_counter)
        self._ws.send(json.dumps({"id": cid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._ws.settimeout(max(0.1, deadline - time.time()))
            raw = self._ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == cid:
                if "error" in msg:
                    raise RuntimeError(f"CDP error for {method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"CDP command {method} timed out")

    def navigate(self, url: str, *, wait_load: bool = True) -> None:
        self._send("Page.navigate", {"url": url})
        if wait_load:
            self._wait_for_ready()

    def _wait_for_ready(self, timeout: float = 20) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.eval_js("document.readyState") == "complete":
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.1)
        raise TimeoutError("page did not finish loading")

    def eval_js(self, expression: str, *, await_promise: bool = False, timeout: float = 20):
        result = self._send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
            "awaitPromise": await_promise,
        }, timeout=timeout)
        exc = result.get("exceptionDetails")
        if exc:
            raise RuntimeError(f"JS error evaluating {expression!r}: {json.dumps(exc)[:1000]}")
        return result.get("result", {}).get("value")

    def screenshot_png(self) -> bytes:
        result = self._send("Page.captureScreenshot", {"format": "png"})
        return base64.b64decode(result["data"])

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self._profile_dir, ignore_errors=True)
