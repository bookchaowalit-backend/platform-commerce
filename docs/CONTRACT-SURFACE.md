# Contract surface: book-commerce-platform

This page documents the API, event, CLI, storage and configuration surface that
`book-commerce-platform` owns or consumes. The machine-readable list is `interfaces` in
[`contract.json`](../contract.json); `scripts/check.py` fails when an interface
listed there is missing from this page.

- Platform: `commerce` (contract `book-platform.contract.v1`, API `v1`)
- Status: `scaffolded`; source status: `adjacent-domain-repository`
- Current implementation: `solo-empire` at `projects/product/engineering/book-dev/github/bookchaowalit/book-apps/tools/book-ecommerce-scraping`
- Depends on: `identity`, `payment`, `observability`

Interfaces marked `current-in-solo-empire` are served by the `solo-empire`
control plane today. This repository does not serve them yet; they are the
compatibility surface a migration must preserve. The `source` column is a path
in the implementing repository.

## Interfaces

No interface is declared yet (see notes below).

## Behaviour notes

Derived from the current source; re-check the source before changing a
consumer.

- The registry's current source is an adjacent domain repository
  (`book-apps/tools/book-ecommerce-scraping`), which is not part of the
  `solo-empire` checkout. No catalog, cart, pricing, order or promotion API is
  served by `solo-empire` today, so no interface is declared yet.
- The first contract slice must be derived from that repository once it is
  available locally; do not invent routes before then.
- Boundary rules: Commerce owns product, price, cart and order state; it must
  call Payment for payment intents and must not create ledger entries.

## Migration gates

- order state parity
- payment boundary
- duplicate order protection

## Out of scope

No production provider integration, credential, database writer or customer
payload lives in this repository. Record parity, privacy and rollback evidence
in the parent platform registry before any cutover.
