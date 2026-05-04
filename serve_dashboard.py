"""
Serve the dashboard and predictions JSON on the LAN.

Bind 0.0.0.0 so another PC can use http://<this-computer-ip>:8765/
(localhost only works on the same machine).

Usage:
  python serve_dashboard.py
  python serve_dashboard.py --port 8765

Run compute_worker.py so out/predictions.json exists.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from config import DASHBOARD_HOST, DASHBOARD_PORT, OUTPUT_DIR, PREDICTIONS_JSON

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DASHBOARD_HOST)
    parser.add_argument("--port", type=int, default=DASHBOARD_PORT)
    parser.add_argument(
        "--predictions",
        default=os.path.join(OUTPUT_DIR, PREDICTIONS_JSON),
        help="Path to predictions JSON (served at /predictions.json).",
    )
    args = parser.parse_args()

    predictions_path = os.path.abspath(args.predictions)
    web_dir = os.path.abspath(WEB_DIR)

    class DashboardHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            clean = self.path.split("?", 1)[0].split("#", 1)[0]
            if clean == "/predictions.json":
                if not os.path.isfile(predictions_path):
                    self.send_error(404, "predictions not generated yet — run compute_worker.py")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with open(predictions_path, "rb") as f:
                    self.wfile.write(f.read())
                return

            if clean == "/":
                clean = "/index.html"
            rel = clean.lstrip("/").replace("\\", "/")
            fp = os.path.normpath(os.path.join(web_dir, rel))
            if not fp.startswith(web_dir) or not os.path.isfile(fp):
                self.send_error(404)
                return
            ctype = mimetypes.guess_type(fp)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            with open(fp, "rb") as f:
                self.wfile.write(f.read())

        def log_message(self, fmt, *args):
            print(fmt % args)

    os.makedirs(web_dir, exist_ok=True)
    index_html = os.path.join(web_dir, "index.html")
    if not os.path.isfile(index_html):
        raise SystemExit(f"Missing {index_html}")

    httpd = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Serving http://{args.host}:{args.port}/")
    print(f"  predictions: {predictions_path}")
    print(f"  web root:    {web_dir}")
    print("Viewer PC: open http://<THIS_MACHINE_LAN_IP>:%s/" % args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
