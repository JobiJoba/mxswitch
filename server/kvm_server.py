#!/usr/bin/env python3
"""
KVM orchestration server for Mac.

Switches the LG monitor via BetterDisplay's HTTP API and Logitech Easy-Switch
devices via the local mxswitch binary.

  GET /mac      -> HDMI (ddcAlt) + Logitech channel for Mac
  GET /windows  -> USB-C (ddcAlt) + Logitech channel for Windows
  GET /health   -> liveness
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "config.json"


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        cfg = json.load(f)

    mx = Path(cfg.get("mxswitch_path", "../mxswitch"))
    if not mx.is_absolute():
        mx = (path.parent / mx).resolve()
    cfg["mxswitch_path"] = str(mx)

    if "targets" not in cfg or "mac" not in cfg["targets"] or "windows" not in cfg["targets"]:
        raise SystemExit("config.json must define targets.mac and targets.windows")

    return cfg


def set_display(base: str, ddc_alt: int) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/set?ddcAlt={ddc_alt}&vcp=inputSelectAlt"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "ok": 200 <= resp.status < 300,
                "status": resp.status,
                "url": url,
                "body": body.strip() or None,
            }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": e.code,
            "url": url,
            "error": body.strip() or str(e),
        }
    except Exception as e:  # noqa: BLE001 — surface any network failure to client
        return {"ok": False, "url": url, "error": str(e)}


def run_mxswitch(binary: str, channel: int) -> dict[str, Any]:
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        return {
            "ok": False,
            "error": f"mxswitch not found or not executable: {binary}",
        }
    try:
        proc = subprocess.run(
            [binary, str(channel)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        return {
            "ok": proc.returncode == 0,
            "channel": channel,
            "returncode": proc.returncode,
            "stdout": out or None,
            "stderr": err or None,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "channel": channel, "error": str(e)}


def switch_target(cfg: dict[str, Any], name: str) -> dict[str, Any]:
    target = cfg["targets"][name]
    display = set_display(cfg["betterdisplay_base"], int(target["ddc_alt"]))
    logitech = run_mxswitch(cfg["mxswitch_path"], int(target["channel"]))
    ok = bool(display.get("ok")) and bool(logitech.get("ok"))
    return {
        "ok": ok,
        "target": name,
        "display": display,
        "logitech": logitech,
    }


class Handler(BaseHTTPRequestHandler):
    config: dict[str, Any] = {}

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, indent=2).encode("utf-8") + b"\n"
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler API
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path == "/health":
            self._send_json(200, {"ok": True, "status": "up"})
            return

        if path in ("/mac", "/windows"):
            name = path.lstrip("/")
            result = switch_target(self.config, name)
            self._send_json(200 if result["ok"] else 502, result)
            return

        self._send_json(
            404,
            {
                "ok": False,
                "error": "not found",
                "routes": ["/mac", "/windows", "/health"],
            },
        )


def main() -> None:
    config_path = Path(os.environ.get("KVM_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_file():
        raise SystemExit(f"config not found: {config_path}")

    cfg = load_config(config_path)
    Handler.config = cfg

    host = cfg.get("host", "0.0.0.0")
    port = int(cfg.get("port", 55778))
    server = ThreadingHTTPServer((host, port), Handler)

    print(
        f"kvm_server listening on http://{host}:{port}\n"
        f"  config     : {config_path}\n"
        f"  mxswitch   : {cfg['mxswitch_path']}\n"
        f"  betterdisplay: {cfg['betterdisplay_base']}\n"
        f"  /mac       : ddcAlt={cfg['targets']['mac']['ddc_alt']} "
        f"channel={cfg['targets']['mac']['channel']}\n"
        f"  /windows   : ddcAlt={cfg['targets']['windows']['ddc_alt']} "
        f"channel={cfg['targets']['windows']['channel']}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
        server.shutdown()


if __name__ == "__main__":
    main()
