from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import string
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from nacl.signing import SigningKey


DEFAULT_IDP_BASE = "https://auth.dev.digik.cantor8.tech"
WORKSHOP_SECRET = "0JElLeAZK7fcRF4ngghM2s7XWxPgDYSD"
DEFAULT_VALIDATOR_API_BASE = "https://api.validator.dev.digik.cantor8.tech/api/validator"
DEFAULT_PARTY_HINT = "jacky"

OUTPUT_DIR = Path("outputs")
RESULT_PATH = OUTPUT_DIR / "result.json"

HASH_KEYS = (
    "hash",
    "transaction_hash",
    "transactionHash",
    "topology_transaction_hash",
    "topologyTransactionHash",
    "topology_transaction_hash_hex",
    "topologyTransactionHashHex",
    "tx_hash",
    "txHash",
)

TOPOLOGY_TRANSACTION_KEYS = (
    "topology_transaction",
    "topologyTransaction",
    "topology_tx",
    "topologyTx",
    "transaction",
    "transaction_proto",
    "transactionProto",
    "serialized_transaction",
    "serializedTransaction",
    "topology_transaction_proto",
    "topologyTransactionProto",
)

PARTY_ID_KEYS = (
    "party_id",
    "partyId",
    "party",
    "external_party_id",
    "externalPartyId",
)


class LabError(Exception):
    """Expected lab failure with a useful message."""


class ApiError(LabError):
    def __init__(self, message: str, status_code: int, url: str, response_body: Any):
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.response_body = response_body

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "api_error",
            "message": str(self),
            "status_code": self.status_code,
            "url": self.url,
            "response_body": self.response_body,
        }


@dataclass
class AuthCandidate:
    name: str
    token_url: str
    form_body: dict[str, str]


@dataclass
class Settings:
    idp_base: str
    validator_api_base: str
    party_hint: str
    http_timeout_seconds: float
    env_client_secret: str

    @property
    def generate_url(self) -> str:
        return f"{self.validator_api_base.rstrip('/')}/v0/admin/external-party/topology/generate"

    @property
    def submit_url(self) -> str:
        return f"{self.validator_api_base.rstrip('/')}/v0/admin/external-party/topology/submit"


@dataclass
class TopologyTransaction:
    index: int
    original: dict[str, Any]
    hash_key: str
    hash_value: str
    topology_transaction_key: str | None
    topology_transaction_value: Any | None


@dataclass
class SignedTopologyTransaction:
    topology_transaction: TopologyTransaction
    hash_encoding: str
    signature_hex: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal Cantor8/Canton external-party topology lab script."
    )
    parser.add_argument(
        "--party-hint",
        default=None,
        help="Optional party hint. Overrides PARTY_HINT in .env.",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Generate and sign the topology transaction but skip submit.",
    )
    return parser.parse_args()


def load_settings(party_hint_override: str | None) -> Settings:
    load_dotenv()

    client_secret = os.getenv("CLIENT_SECRET", "").strip()
    if client_secret == "paste-client-secret-here":
        client_secret = ""

    timeout_raw = os.getenv("HTTP_TIMEOUT_SECONDS", "30").strip()
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise LabError("HTTP_TIMEOUT_SECONDS must be a number.") from exc

    party_hint = (
        party_hint_override
        if party_hint_override is not None
        else os.getenv("PARTY_HINT", DEFAULT_PARTY_HINT)
    ).strip()
    if not party_hint:
        party_hint = DEFAULT_PARTY_HINT

    return Settings(
        idp_base=os.getenv("IDP_BASE", DEFAULT_IDP_BASE).strip().rstrip("/"),
        validator_api_base=os.getenv(
            "VALIDATOR_API_BASE", DEFAULT_VALIDATOR_API_BASE
        )
        .strip()
        .rstrip("/"),
        party_hint=party_hint,
        http_timeout_seconds=timeout,
        env_client_secret=client_secret,
    )


def build_auth_candidates(settings: Settings) -> list[AuthCandidate]:
    master_url = (
        f"{settings.idp_base.rstrip('/')}/realms/master/protocol/openid-connect/token"
    )
    hackathon_url = (
        f"{settings.idp_base.rstrip('/')}/realms/hackathon/protocol/openid-connect/token"
    )

    candidates = [
        AuthCandidate(
            name="candidate_1",
            token_url=master_url,
            form_body={
                "grant_type": "client_credentials",
                "client_id": "hackathon",
                "client_secret": WORKSHOP_SECRET,
            },
        ),
        AuthCandidate(
            name="candidate_2",
            token_url=master_url,
            form_body={
                "grant_type": "client_credentials",
                "client_id": WORKSHOP_SECRET,
            },
        ),
        AuthCandidate(
            name="candidate_3",
            token_url=master_url,
            form_body={
                "grant_type": "client_credentials",
                "client_id": WORKSHOP_SECRET,
                "client_secret": settings.env_client_secret,
            },
        ),
        AuthCandidate(
            name="candidate_4",
            token_url=hackathon_url,
            form_body={
                "grant_type": "client_credentials",
                "client_id": "hackathon",
                "client_secret": WORKSHOP_SECRET,
            },
        ),
        AuthCandidate(
            name="candidate_5",
            token_url=hackathon_url,
            form_body={
                "grant_type": "client_credentials",
                "client_id": WORKSHOP_SECRET,
            },
        ),
    ]

    if not settings.env_client_secret:
        candidates = [c for c in candidates if c.name != "candidate_3"]

    return candidates


def print_step(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def pretty_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def parse_response_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw_text": response.text}


def post_json(
    client: httpx.Client,
    url: str,
    *,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, str] | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = client.post(url, headers=headers, json=json_body, data=form_body)
    body = parse_response_body(response)

    if response.is_error:
        raise ApiError(
            f"POST {url} failed with HTTP {response.status_code}.",
            response.status_code,
            url,
            body,
        )

    return body


def get_json(
    client: httpx.Client,
    url: str,
    *,
    token: str | None = None,
) -> Any:
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = client.get(url, headers=headers)
    body = parse_response_body(response)

    if response.is_error:
        raise ApiError(
            f"GET {url} failed with HTTP {response.status_code}.",
            response.status_code,
            url,
            body,
        )

    return body


def get_access_token(client: httpx.Client, settings: Settings) -> tuple[str, str]:
    print_step("1. Request OAuth token with client_credentials")
    candidates = build_auth_candidates(settings)

    for candidate in candidates:
        secret_note = (
            " (client_secret from .env)"
            if candidate.name == "candidate_3"
            else ""
        )
        print(f"Trying {candidate.name}{secret_note}: POST {candidate.token_url}")

        response = client.post(
            candidate.token_url,
            data=candidate.form_body,
        )
        body_text = response.text[:500]
        if response.is_error:
            print(f"  {candidate.name} failed")
            print(f"  status code: {response.status_code}")
            print(f"  response body (first 500 chars): {body_text}")
            continue

        token_response = parse_response_body(response)
        access_token = token_response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            print(f"  {candidate.name} failed")
            print(f"  status code: {response.status_code}")
            print(
                "  response body (first 500 chars): "
                + json.dumps(token_response)[:500]
            )
            continue

        print(f"Got JWT using {candidate.name}")
        print("Access token received but not printed.")
        return access_token, candidate.name

    raise LabError("All auth candidates failed. See printed errors above.")


def generate_keypair() -> tuple[SigningKey, str]:
    print_step("2. Generate local Ed25519 keypair")
    signing_key = SigningKey.generate()
    public_key_hex = bytes(signing_key.verify_key).hex()
    print(f"Public key hex: {public_key_hex}")
    print("Private signing key stays in memory only and is not saved.")
    return signing_key, public_key_hex


def generate_topology(
    client: httpx.Client,
    settings: Settings,
    token: str,
    public_key_hex: str,
) -> Any:
    print_step("3. Generate external-party topology transaction")
    payload = {
        "party_hint": settings.party_hint,
        "public_key": public_key_hex,
    }
    print(f"Generate URL: {settings.generate_url}")
    print("Generate payload:")
    print(pretty_json(payload))

    response = post_json(client, settings.generate_url, token=token, json_body=payload)
    print("Generate response:")
    print(pretty_json(response))
    return response


def submit_topology(
    client: httpx.Client,
    settings: Settings,
    token: str,
    payload: dict[str, Any],
) -> Any:
    print_step("5. Submit signed topology transactions")
    print(f"Submit URL: {settings.submit_url}")
    print("Submit payload:")
    print(pretty_json(payload))

    response = post_json(client, settings.submit_url, token=token, json_body=payload)
    print("Submit response:")
    print(pretty_json(response))
    return response


def iter_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            found.append(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    return found


def find_first_string_by_keys(value: Any, keys: tuple[str, ...]) -> str | None:
    for item in iter_dicts(value):
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def get_string_field(item: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str] | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value:
            return key, value
    return None


def get_any_field(item: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return key, value
    return None


def collect_field_paths(value: Any) -> list[str]:
    paths: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}"
                paths.append(child_path)
                walk(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node[:5]):
                child_path = f"{path}[{index}]"
                paths.append(child_path)
                walk(child, child_path)

    walk(value, "$")
    return paths


def extract_topology_transactions(generate_response: Any) -> list[TopologyTransaction]:
    transactions: list[TopologyTransaction] = []
    seen_ids: set[int] = set()

    for item in iter_dicts(generate_response):
        hash_field = get_string_field(item, HASH_KEYS)
        if not hash_field:
            continue

        item_id = id(item)
        if item_id in seen_ids:
            continue
        seen_ids.add(item_id)

        topology_field = get_any_field(item, TOPOLOGY_TRANSACTION_KEYS)
        transactions.append(
            TopologyTransaction(
                index=len(transactions),
                original=item,
                hash_key=hash_field[0],
                hash_value=hash_field[1],
                topology_transaction_key=topology_field[0] if topology_field else None,
                topology_transaction_value=topology_field[1] if topology_field else None,
            )
        )

    if not transactions:
        field_paths = collect_field_paths(generate_response)
        shown_paths = "\n".join(f"  - {path}" for path in field_paths[:80])
        raise LabError(
            "Could not find a topology transaction hash in the generate response.\n"
            "Known hash field names tried: "
            + ", ".join(HASH_KEYS)
            + "\nFields found:\n"
            + (shown_paths or "  (no JSON object fields found)")
        )

    print_step("4. Inspect generated topology transactions and sign hashes")
    for tx in transactions:
        print(
            "Found transaction "
            f"#{tx.index}: hash field '{tx.hash_key}', "
            f"topology transaction field '{tx.topology_transaction_key or 'not found'}'"
        )

    missing_topology_payloads = [
        tx for tx in transactions if tx.topology_transaction_value is None
    ]
    if missing_topology_payloads:
        field_paths = collect_field_paths(generate_response)
        shown_paths = "\n".join(f"  - {path}" for path in field_paths[:80])
        raise LabError(
            "Found transaction hash(es), but could not find the topology transaction "
            "payload needed for submit.\n"
            "Known topology transaction field names tried: "
            + ", ".join(TOPOLOGY_TRANSACTION_KEYS)
            + "\nFields found:\n"
            + (shown_paths or "  (no JSON object fields found)")
        )

    return transactions


def decode_hash_for_signing(hash_value: str) -> tuple[bytes, str]:
    value = hash_value.strip()
    if value.startswith("0x"):
        value = value[2:]

    is_hex = (
        len(value) >= 2
        and len(value) % 2 == 0
        and all(ch in string.hexdigits for ch in value)
    )
    if is_hex:
        try:
            return bytes.fromhex(value), "hex"
        except ValueError:
            pass

    try:
        return base64.b64decode(value, validate=True), "base64"
    except (binascii.Error, ValueError):
        return value.encode("utf-8"), "utf-8"


def sign_topology_transactions(
    signing_key: SigningKey,
    transactions: list[TopologyTransaction],
) -> list[SignedTopologyTransaction]:
    signed: list[SignedTopologyTransaction] = []

    for tx in transactions:
        hash_bytes, encoding = decode_hash_for_signing(tx.hash_value)
        signature_hex = signing_key.sign(hash_bytes).signature.hex()
        print(
            f"Signed transaction #{tx.index}: hash decoded as {encoding}, "
            f"signature hex {signature_hex}"
        )
        signed.append(
            SignedTopologyTransaction(
                topology_transaction=tx,
                hash_encoding=encoding,
                signature_hex=signature_hex,
            )
        )

    return signed


def build_submit_payload(
    signed_transactions: list[SignedTopologyTransaction],
    public_key_hex: str,
) -> dict[str, Any]:
    signed_topology_txs: list[dict[str, Any]] = []

    for signed in signed_transactions:
        tx = signed.topology_transaction
        signed_topology_txs.append(
            {
                "topology_tx": tx.topology_transaction_value,
                "signed_hash": signed.signature_hex,
            }
        )

    return {
        "public_key": public_key_hex,
        "signed_topology_txs": signed_topology_txs,
    }


CONTRACT_ID_KEYS = (
    "contract_id",
    "contractId",
    "setup_proposal_contract_id",
    "setupProposalContractId",
)


def extract_contract_id(response: Any) -> str | None:
    return find_first_string_by_keys(response, CONTRACT_ID_KEYS)


def extract_tx_hash(response: Any) -> str | None:
    return find_first_string_by_keys(response, HASH_KEYS)


def extract_transaction(response: Any) -> Any | None:
    for item in iter_dicts(response):
        for key in ("transaction", "prepared_transaction", "preparedTransaction"):
            value = item.get(key)
            if value not in (None, ""):
                return value
    return None


def setup_preapproval(
    client: httpx.Client,
    settings: Settings,
    token: str,
    party_id: str,
    signing_key: SigningKey,
    public_key_hex: str,
) -> dict[str, Any]:
    print_step("7. Set up PreApproval")
    base = settings.validator_api_base.rstrip("/")
    preapproval_result: dict[str, Any] = {}

    setup_url = f"{base}/v0/admin/external-party/setup-proposal"
    setup_payload = {"user_party_id": party_id}
    print(f"POST {setup_url}")
    print(pretty_json(setup_payload))
    setup_response = post_json(client, setup_url, token=token, json_body=setup_payload)
    print("Setup proposal response:")
    print(pretty_json(setup_response))
    preapproval_result["setup_proposal_response"] = setup_response

    contract_id = extract_contract_id(setup_response)
    if not contract_id:
        raise LabError(
            "Setup proposal succeeded but no contract_id was found in the response.\n"
            + pretty_json(setup_response)
        )

    prepare_url = f"{base}/v0/admin/external-party/setup-proposal/prepare-accept"
    prepare_payload = {
        "contract_id": contract_id,
        "user_party_id": party_id,
        "verbose_hashing": True,
    }
    print(f"POST {prepare_url}")
    print(pretty_json(prepare_payload))
    prepare_response = post_json(
        client, prepare_url, token=token, json_body=prepare_payload
    )
    print("Prepare accept response:")
    print(pretty_json(prepare_response))
    preapproval_result["prepare_accept_response"] = prepare_response

    tx_hash = extract_tx_hash(prepare_response)
    transaction = extract_transaction(prepare_response)
    if not tx_hash:
        raise LabError(
            "Prepare accept succeeded but no tx_hash was found in the response.\n"
            + pretty_json(prepare_response)
        )
    if transaction is None:
        raise LabError(
            "Prepare accept succeeded but no transaction was found in the response.\n"
            + pretty_json(prepare_response)
        )

    hash_bytes, hash_encoding = decode_hash_for_signing(tx_hash)
    signed_tx_hash = signing_key.sign(hash_bytes).signature.hex()
    print(f"Signed tx_hash (decoded as {hash_encoding}): {signed_tx_hash}")

    submit_url = f"{base}/v0/admin/external-party/setup-proposal/submit-accept"
    submit_payload = {
        "submission": {
            "party_id": party_id,
            "transaction": transaction,
            "signed_tx_hash": signed_tx_hash,
            "public_key": public_key_hex,
        }
    }
    print(f"POST {submit_url}")
    print(pretty_json(submit_payload))
    submit_accept_response = post_json(
        client, submit_url, token=token, json_body=submit_payload
    )
    print("Submit accept response:")
    print(pretty_json(submit_accept_response))
    preapproval_result["submit_accept_response"] = submit_accept_response

    lookup_url = f"{base}/v0/admin/transfer-preapprovals/by-party/{party_id}"
    print(f"GET {lookup_url}")
    lookup_response = get_json(client, lookup_url, token=token)
    print("PreApproval lookup response:")
    print(pretty_json(lookup_response))
    preapproval_result["preapproval_lookup_response"] = lookup_response
    preapproval_result["preapproval_set_up"] = True

    return preapproval_result


def check_balance(
    client: httpx.Client,
    settings: Settings,
    token: str,
    party_id: str,
) -> dict[str, Any]:
    print_step("8. Check balance")
    url = (
        f"{settings.validator_api_base.rstrip('/')}"
        f"/v0/admin/external-party/balance?party_id={party_id}"
    )
    print(f"GET {url}")
    try:
        balance_response = get_json(client, url, token=token)
        print("Balance response:")
        print(pretty_json(balance_response))
        return {"balance_response": balance_response}
    except ApiError as exc:
        print(f"Balance check failed: {exc}")
        print("Response body:")
        print(pretty_json(exc.response_body))
        return {"balance_error": exc.as_dict()}


def save_result(result: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(pretty_json(result) + "\n", encoding="utf-8")
    print()
    print(f"Saved result JSON to: {RESULT_PATH}")


def error_to_dict(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ApiError):
        return exc.as_dict()
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }


def run() -> int:
    args = parse_args()

    result: dict[str, Any] = {
        "auth_candidate_used": None,
        "party_hint": None,
        "party_id": None,
        "public_key_hex": None,
        "topology_generate_response": None,
        "topology_submit_response": None,
        "setup_proposal_response": None,
        "prepare_accept_response": None,
        "submit_accept_response": None,
        "preapproval_lookup_response": None,
        "preapproval_set_up": False,
        "balance_response": None,
        "balance_error": None,
        "errors": [],
    }

    try:
        settings = load_settings(args.party_hint)
        result["party_hint"] = settings.party_hint

        timeout = httpx.Timeout(settings.http_timeout_seconds)
        with httpx.Client(timeout=timeout) as client:
            access_token, auth_candidate = get_access_token(client, settings)
            result["auth_candidate_used"] = auth_candidate

            signing_key, public_key_hex = generate_keypair()
            result["public_key_hex"] = public_key_hex

            generate_response = generate_topology(
                client, settings, access_token, public_key_hex
            )
            result["topology_generate_response"] = generate_response
            result["party_id"] = find_first_string_by_keys(generate_response, PARTY_ID_KEYS)

            topology_transactions = extract_topology_transactions(generate_response)
            signed_transactions = sign_topology_transactions(
                signing_key, topology_transactions
            )
            submit_payload = build_submit_payload(signed_transactions, public_key_hex)

            if args.no_submit:
                print_step("5. Submit skipped")
                print("--no-submit was provided. Signed payload was not sent.")
                result["topology_submit_response"] = {
                    "skipped": True,
                    "submit_payload": submit_payload,
                }
            else:
                submit_response = submit_topology(
                    client, settings, access_token, submit_payload
                )
                result["topology_submit_response"] = submit_response
                result["party_id"] = result["party_id"] or find_first_string_by_keys(
                    submit_response, PARTY_ID_KEYS
                )

            party_id = result["party_id"]
            if not party_id:
                raise LabError(
                    "No party_id returned from topology generate/submit. "
                    "Check outputs/result.json for response fields."
                )

            if not args.no_submit:
                try:
                    preapproval_result = setup_preapproval(
                        client,
                        settings,
                        access_token,
                        party_id,
                        signing_key,
                        public_key_hex,
                    )
                    result.update(preapproval_result)
                except BaseException as preapproval_exc:
                    print()
                    print("PreApproval setup failed:")
                    print(str(preapproval_exc))
                    result["errors"].append(error_to_dict(preapproval_exc))

                balance_result = check_balance(
                    client, settings, access_token, party_id
                )
                result.update(balance_result)

            print_step("9. Result — paste this PartyId into Telegram")
            print()
            print("=" * 78)
            print(f"PARTY ID: {party_id}")
            print("=" * 78)
            print()
            if result.get("preapproval_set_up"):
                print("PreApproval: set up successfully")
            elif args.no_submit:
                print("PreApproval: skipped (--no-submit)")
            else:
                print("PreApproval: NOT set up — check errors above")
            if result.get("balance_response"):
                print("Balance check: succeeded")
            elif result.get("balance_error"):
                print("Balance check: failed (see outputs/result.json)")
            else:
                print("Balance check: not run")

            return_code = 0 if not result["errors"] else 1

    except BaseException as exc:
        print()
        print("ERROR:")
        print(str(exc))
        result["errors"].append(error_to_dict(exc))
        return_code = 1

    finally:
        save_result(result)

    return return_code


if __name__ == "__main__":
    sys.exit(run())

