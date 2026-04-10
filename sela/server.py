#!/usr/bin/env python3
"""
Sela — Flask server.
Serves the UI (index.html) and streams agent analysis via SSE.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python server.py
    # then open http://localhost:5055
"""

import json
import os
import sys

from flask import Flask, Response, request, send_from_directory, stream_with_context

sys.path.insert(0, os.path.dirname(__file__))
from agents import run_round_table_events
import config

app = Flask(__name__)
ROOT = os.path.dirname(__file__)


@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True) or {}
    stocks = data.get("stocks", config.WATCHLIST)
    budget = int(data.get("budget", config.LUMP_SUM_NIS))
    monthly = int(data.get("monthly", config.MONTHLY_NIS))

    def generate():
        try:
            for event_type, payload in run_round_table_events(stocks, budget, monthly):
                line = json.dumps({"event": event_type, **payload})
                yield f"data: {line}\n\n"
        except Exception as exc:
            err = json.dumps({"event": "error", "message": str(exc)})
            yield f"data: {err}\n\n"
        finally:
            yield "data: {\"event\": \"done\"}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5055))
    print(f"\n  sela  →  http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
