"""Check CC balance for a party created by src/main.py."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from main import check_balance, get_access_token, load_settings


def main() -> int:
    load_dotenv()
    party_id = os.getenv("PARTY_ID", "").strip()
    if not party_id:
        print("Set PARTY_ID in .env after src/main.py prints one.")
        return 1

    try:
        settings = load_settings(None)
        timeout = httpx.Timeout(settings.http_timeout_seconds)
        with httpx.Client(timeout=timeout) as client:
            token, auth_candidate = get_access_token(client, settings)
            print(f"Auth: {auth_candidate}")
            print(f"Party ID: {party_id}")
            result = check_balance(client, settings, token, party_id)
            if result.get("balance_error"):
                return 1
            balance = result.get("balance_response", {})
            print()
            print(f"Total available CC: {balance.get('total_available_coin', 'unknown')}")
            print(json.dumps(balance, indent=2))
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
