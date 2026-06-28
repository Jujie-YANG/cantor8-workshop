# Cantor8 / Canton Low-Level Lab

Minimal Python repo for the Cantor8 / Canton workshop (Workshop 1).

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

Optional: copy `.env.example` to `.env` if you want to override defaults or supply an optional `CLIENT_SECRET`. The script tries several auth candidates automatically.

## What is PartyId?

Your **PartyId** is the Canton party identifier returned after topology submit. The workshop team sends CC (Canton Coin) to this ID once you paste it in Telegram.

## What is PreApproval?

**PreApproval** lets the validator accept incoming transfers to your party without a manual accept step each time. Alex reminded everyone to set up PreApproval **before** submitting your PartyId for CC. This script runs the PreApproval flow after topology submit.

## What to paste into Telegram

When the script finishes, copy the line printed as:

```text
PARTY ID: ...
```

Paste that PartyId into the workshop Telegram channel so the team can send CC.

## Submit your GitHub repo link

The Google Form asks for:

- GitHub repo link (push this repo; do not commit `.env`, `outputs/`, `venv/`, or private keys)
- Documentation feedback (`feedback.md`)
- Optional social post link
- Telegram joined yes/no

## Output

Results are saved to `outputs/result.json` (gitignored). Optional helpers:

```bash
python src/check_balance.py   # requires PARTY_ID in .env
python src/check_acs.py
```
