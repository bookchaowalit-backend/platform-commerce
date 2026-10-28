# platform-commerce

`Commerce` platform boundary for the Book Platform portfolio.

## Scope

This repository owns the `commerce` capability: catalog, cart, pricing, order, promotion.
The current source implementation is recorded as `projects/product/engineering/book-dev/github/bookchaowalit/public/book-apps/tools/book-ecommerce-scraping` in the
parent registry. This checkout is a local scaffold; it contains no production
provider integration, database writer, credential, or customer payload.

## Boundary

- Owner: `bookchaowalit-backend`
- Repository: `platform-commerce`
- Target remote: `https://github.com/bookchaowalit-backend/platform-commerce.git` (published; runtime not activated)
- Contract: `book-platform.contract.v1`
- Status: `scaffolded`
- Data owner: the platform boundary identified in `contract.json`

The platform communicates through versioned API or event contracts. Consumers
must not import another platform's database, migration, or private runtime
module. `solo-empire` remains the control plane and compatibility adapter until
parity and rollback evidence permit a cutover.

## Local verification

Run from this repository (Python 3.11+, no third-party packages):

```bash
bash scripts/check.sh
```

The check validates `contract.json` against
[`schema/book-platform.contract.v1.schema.json`](schema/book-platform.contract.v1.schema.json),
confirms that the README and [`docs/CONTRACT-SURFACE.md`](docs/CONTRACT-SURFACE.md)
agree with the contract, and runs the unit tests in `tests/`. GitHub Actions
runs the same command on every push and pull request
(`.github/workflows/check.yml`).

`scripts/check_schema_pin.py` fails when the vendored schema no longer
matches the sha256 pinned in `schema/book-platform.contract.v1.schema.json.sha256`
(the canonical copy lives in `bookchaowalit-backend-core/contracts/`; change it
there first, then copy the schema and its pin here). Pass
`--canonical ../bookchaowalit-backend-core` to also compare with a local
checkout. `python3 scripts/check_registry_alignment.py --solo-empire ../solo-empire`
compares this contract with the parent platform registry (local only; read-only).

The check validates repository shape and contract metadata only. It does not
claim deployment, provider connectivity, data migration, or production
readiness.

## Contract surface

Dependencies: `identity`, `payment`, `observability`. The interfaces this boundary owns or consumes, with
their auth, idempotency and error behaviour, are listed in
[`docs/CONTRACT-SURFACE.md`](docs/CONTRACT-SURFACE.md). Planned work is tracked
in [`docs/UPGRADE-PLAN.md`](docs/UPGRADE-PLAN.md).

## Migration gate

Before activating a remote or changing a consumer, add sanitized fixtures for
success, duplicate delivery, timeout and provider failure; prove tenant/privacy
isolation; compare the old and new contract; and rehearse rollback on a
disposable state store. Record the evidence in the parent platform registry.

## Runtime pilot (implemented locally, not deployed)

A bounded Python 3.12+ / PostgreSQL 16+ runtime for catalog, cart, pricing,
promotion and order lives in `src/platform_commerce`. Orders stop at `placed` or
`cancelled`: payment capture stays outside this boundary (owner decision D8). The
contract status above stays `scaffolded` until activation evidence exists. See the
[runtime guide](docs/runtime.md) for the API, lifecycle and verification record;
`.github/workflows/shared-runtime.yml` runs its tests against PostgreSQL 16.
