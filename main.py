#!/usr/bin/env python3
"""Grant Scout 2 - Life Sciences Grant Opportunity Scanner.

Usage:
    python main.py                     # Full pipeline run (all sources)
    python main.py --sources nih sbir  # Run specific sources only
    python main.py --no-semantic       # Skip Claude API scoring
    python main.py --serve             # Launch dashboard on localhost:8000
"""

import argparse
import http.server
import json
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

from src.exporters import export_csv, export_json, export_markdown
from src.pipeline import Pipeline

# Shared state for pipeline refresh
_refresh_lock = threading.Lock()
_refresh_status = {"state": "idle", "started_at": None, "error": None}


def main():
    parser = argparse.ArgumentParser(
        description="Grant Scout 2 - Life Sciences Grant Scanner"
    )
    parser.add_argument(
        "--sources", nargs="+",
        choices=[
            "nih_guide", "grants_gov", "eu_portal", "sbir",
            "grand_challenges", "innovation_fund_dk", "wellcome_leap",
        ],
        help="Run specific sources only",
    )
    parser.add_argument(
        "--no-semantic", action="store_true",
        help="Skip Claude API semantic scoring",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="Start local dashboard server",
    )
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port for dashboard server (default: 8000)",
    )
    parser.add_argument(
        "--config-dir", default="config",
        help="Config directory path",
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Output directory path",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.serve:
        serve_dashboard(args.port, config_dir=args.config_dir)
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pipeline = Pipeline(config_dir=args.config_dir)
    opportunities = pipeline.run(
        sources=args.sources,
        skip_semantic=args.no_semantic,
    )

    # Export all formats
    export_json(opportunities, str(output_dir / "opportunities.json"), pipeline.run_log)
    export_csv(opportunities, str(output_dir / "opportunities.csv"))
    export_markdown(opportunities, str(output_dir / "report.md"))

    # Dashboard data
    dashboard_data = Path("dashboard/data")
    dashboard_data.mkdir(parents=True, exist_ok=True)
    export_json(opportunities, str(dashboard_data / "opportunities.json"), pipeline.run_log)

    # Run log
    with open(output_dir / "run_log.json", "w") as f:
        json.dump(pipeline.run_log, f, indent=2)

    print(f"\nDone! {len(opportunities)} opportunities found.")
    print(f"  High priority: {sum(1 for o in opportunities if o.high_priority)}")
    print(f"  Startup eligible: {sum(1 for o in opportunities if o.startup_eligible)}")
    print(f"  Consortium eligible: {sum(1 for o in opportunities if o.consortium_eligible)}")
    print(f"  Output: {output_dir}/")


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """Serves static files and provides /api/refresh and /api/status endpoints."""

    config_dir = "config"

    def do_GET(self):
        if self.path == "/api/status":
            self._send_json(_refresh_status)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            self._handle_refresh()
        else:
            self.send_error(404, "Not Found")

    def _handle_refresh(self):
        global _refresh_status
        if _refresh_status["state"] == "running":
            self._send_json({"state": "running", "message": "Refresh already in progress"})
            return

        _refresh_status = {
            "state": "running",
            "started_at": datetime.utcnow().isoformat(),
            "error": None,
        }

        thread = threading.Thread(
            target=_run_pipeline_background,
            args=(self.config_dir,),
            daemon=True,
        )
        thread.start()
        self._send_json({"state": "running", "message": "Refresh started"})

    def _send_json(self, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if "/api/status" not in (args[0] if args else ""):
            super().log_message(format, *args)


def _run_pipeline_background(config_dir):
    global _refresh_status
    with _refresh_lock:
        try:
            pipeline = Pipeline(config_dir=config_dir)
            opportunities = pipeline.run(skip_semantic=True)

            output_dir = Path("output")
            output_dir.mkdir(parents=True, exist_ok=True)
            export_json(opportunities, str(output_dir / "opportunities.json"), pipeline.run_log)
            export_csv(opportunities, str(output_dir / "opportunities.csv"))
            export_markdown(opportunities, str(output_dir / "report.md"))

            dashboard_data = Path("dashboard/data")
            dashboard_data.mkdir(parents=True, exist_ok=True)
            export_json(opportunities, str(dashboard_data / "opportunities.json"), pipeline.run_log)

            with open(output_dir / "run_log.json", "w") as f:
                json.dump(pipeline.run_log, f, indent=2)

            _refresh_status = {
                "state": "done",
                "started_at": _refresh_status["started_at"],
                "completed_at": datetime.utcnow().isoformat(),
                "total": len(opportunities),
                "error": None,
            }
        except Exception as e:
            logging.getLogger(__name__).error(f"Pipeline refresh failed: {e}")
            _refresh_status = {
                "state": "error",
                "started_at": _refresh_status["started_at"],
                "error": str(e),
            }


def serve_dashboard(port: int, config_dir: str = "config"):
    DashboardHandler.config_dir = config_dir
    DashboardHandler.extensions_map.update({".js": "application/javascript"})

    def handler_factory(*args, **kwargs):
        return DashboardHandler(*args, directory="dashboard", **kwargs)

    with http.server.HTTPServer(("", port), handler_factory) as server:
        print(f"Dashboard running at http://localhost:{port}")
        print("Press Ctrl+C to stop")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server.")


if __name__ == "__main__":
    main()
