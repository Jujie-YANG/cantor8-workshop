"""Best-effort placeholder for a later balance check.

The workshop reward flow does not depend on this file. Keep it small and edit the
endpoint once Cantor8 confirms the exact balance API for your party/account.
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    party_id = os.getenv("PARTY_ID", "").strip()
    api_base = os.getenv(
        "VALIDATOR_API_BASE", "https://api.validator.dev.digik.cantor8.tech/api/validator"
    ).rstrip("/")

    if not party_id:
        print("Set PARTY_ID in .env after src/main.py prints one.")
        return 1

    print("Balance check placeholder")
    print(f"Party ID: {party_id}")
    print(f"Validator API base: {api_base}")
    print("Ask Cantor8 for the exact balance endpoint, then add it here.")

    # Example shape only. Do not treat this as confirmed workshop API.
    # with httpx.Client(timeout=30) as client:
    #     response = client.get(f"{api_base}/v0/...")
    #     print(response.status_code)
    #     print(response.text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

