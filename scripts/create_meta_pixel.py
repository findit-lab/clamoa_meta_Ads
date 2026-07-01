"""Create a Meta Pixel/Dataset under an ad account.

usage:
  python3 scripts/create_meta_pixel.py --account-id act_123 --name "clamoa website"
"""
import _bootstrap  # noqa: F401
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request

import config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", required=True, help="Meta ad account id; act_ prefix is optional")
    ap.add_argument("--name", default="clamoa website")
    args = ap.parse_args()

    if not config.META_ACCESS_TOKEN:
        raise SystemExit("META_ACCESS_TOKEN is required")

    account_id = args.account_id
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    params = urllib.parse.urlencode({"access_token": config.META_ACCESS_TOKEN})
    url = f"https://graph.facebook.com/{config.META_GRAPH_API_VERSION}/{account_id}/adspixels?{params}"
    data = urllib.parse.urlencode({"name": args.name}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Meta pixel create failed: HTTP {e.code}: {body}") from e

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    pixel_id = payload.get("id")
    if pixel_id:
        print(f"\nCLAMOA_META_PIXEL_ID={pixel_id}")


if __name__ == "__main__":
    main()
