#!/usr/bin/env python3
"""Launch the PT-Kit graphical simulator dashboard.

    python run_sim_dashboard.py [--host 0.0.0.0] [--port 8902]

Then open the printed URL in a browser. All telemetry is in-memory and
isolated from production ingestion (never calls /api/insert_data).
"""
import argparse

import uvicorn

from app.simulator.live_dashboard import create_app


def main() -> None:
    p = argparse.ArgumentParser(description="PT-Kit simulator dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8902)
    args = p.parse_args()
    print(f"⚗️  PT-Kit Simulator Dashboard  →  http://{args.host}:{args.port}/")
    print("    In-memory only · isolated from production ingestion")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
