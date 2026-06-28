# Cantor8 / Canton Low-Level Lab Feedback

## What worked

- The overall low-level flow is useful: authenticate, generate a party topology transaction, sign locally, submit, and record the party ID.
- Generating an Ed25519 keypair locally with PyNaCl is straightforward.

## What was confusing

- **Credentials were confusing** because `hackathon` and the long string (`0JElLeAZK7fcRF4ngghM2s7XWxPgDYSD`) were shown in the workshop doc but not explicitly labelled as `client_id` vs `client_secret`. It was unclear which value goes where.
- The docs jump between Canton concepts, topology, Admin API, Ledger API, and Token Standard too quickly — hard to know which layer you are working in at each step.
- The workshop says "internal party", but the process slide points to `external-party/topology/generate` and `external-party/topology/submit`. Terminology mismatch.
- It is unclear what exact JSON shape the generate endpoint returns and what signed payload the submit endpoint expects.

## What would improve the docs

- **PreApproval should be highlighted as required** before submitting PartyId for CC. Alex had to remind everyone in Telegram; it should be in the main lab steps, not an afterthought.
- Provide **one happy-path script** covering the full sequence:
  JWT → keypair → topology generate → sign → topology submit → PreApproval → PartyId → CC → balance check
- Add **expected response examples** after each step (token, generate, sign, submit, PreApproval, balance) so debugging mismatched field names is faster.
- Clearly separate concepts, API reference, and lab actions.
- Explicitly say whether signatures should be hex, base64, or another encoding.
- Provide the exact submit request schema for `/v0/admin/external-party/topology/submit`.
