"""Serve the internal Meta Ads performance dashboard."""
import _bootstrap  # noqa: F401
import argparse

import config
from adintel import db


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=config.META_DASHBOARD_HOST)
    ap.add_argument("--port", type=int, default=config.META_DASHBOARD_PORT)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    db.init_db()
    try:
        import uvicorn
    except ImportError as e:
        raise SystemExit("uvicorn 미설치: pip install -r requirements.txt") from e
    uvicorn.run(
        "adintel.performance.dashboard:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

