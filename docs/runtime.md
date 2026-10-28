# Commerce runtime pilot

Status: implemented and locally verified; deployment artifacts staged only. No
production activation is claimed, and `contract.json` stays `scaffolded` (its guard
requires activation evidence). The pattern follows `platform-communication`
(main `b78809e`) and `platform-backend-core` at `d00e0119`.

Scope is this repository's contract capabilities, kept deliberately small:
catalog items with integer minor-unit prices, carts, deterministic pricing with one
simple promotion per cart, and idempotent order placement. **Payment is out of
scope** (owner decision D8): there is no payment intent, capture, refund or ledger
code, and the database refuses any order status other than `placed` or `cancelled`.

## Installation and lifecycle

Python >=3.12, PostgreSQL >=16. Build and review wheels for this repository and
`platform-backend-core==0.1.0` (CI pins commit `d00e0119c2e4`); a release bundles
them and their dependencies in `wheelhouse/` for the `Dockerfile`. Nothing is
published to PyPI. `Dockerfile` and `railway.toml` are reference release assets; no
container build or Railway deployment has been run.

- `python -m platform_commerce migrate`: applies `MIGRATIONS` (namespace `commerce`)
  with the DDL-role `DATABASE_URL`. It is idempotent and never runs at API startup.
- `python -m platform_commerce serve`: needs a separate NOSUPERUSER NOBYPASSRLS
  runtime `DATABASE_URL` (the shared `Database` refuses a privileged role), and
  `JWT_ISSUER`, `JWT_AUDIENCE` and exactly one of `JWT_PUBLIC_KEY` (PEM) or
  `JWT_JWKS_URL` (HTTPS). `PORT` defaults to 8080. Concurrency 100, pool 8, SQL
  timeout 10 s, HTTP boundary 30 s, request body at most 16 KiB. Any startup error
  exits with the fixed message `Service configuration or dependency unavailable`.
- `GET /healthz` (liveness), `GET /readyz`, `GET /metrics` come from the shared core.
  Readiness is 200 only when the applied `commerce` migration versions and checksums
  equal the code's, all six tables have forced RLS, and the runtime role holds schema
  `USAGE`, `SELECT` on `platform_schema_migrations` and every privilege below, each
  checked on its own (a comma-separated privilege list would mean *any*).
- Python: `platform_commerce.app:create_app(database, verifier)`,
  `platform_commerce.store.CommerceStore(database)`,
  `platform_commerce.pricing.quote(currency, lines, promotion)`.

Runtime grants (no ownership, CREATE, TRUNCATE or history writes):

| Table | Privileges |
|---|---|
| `catalog_item` | SELECT, INSERT, UPDATE |
| `promotion` | SELECT, INSERT |
| `cart` | SELECT, INSERT, UPDATE |
| `cart_line` | SELECT, INSERT, UPDATE, DELETE |
| `commerce_order` | SELECT, INSERT, UPDATE |
| `order_line` | SELECT, INSERT |

Tenancy: the workspace is the JWT `ws` claim and the actor is `sub`; no body, path or
header selects a workspace. Every store call runs in `Database.transaction(workspace)`,
which sets `app.workspace_id`; each table has `ENABLE` + `FORCE ROW LEVEL SECURITY`
with a `USING` and `WITH CHECK` policy on it. Another workspace's rows read as 404.

## API

All routes need a bearer token with the listed scope; 401 without a valid token, 403
without the scope. Money is always an integer count of the currency's minor unit
(`unit_price_minor: 12000` with `THB` is 120.00 baht); there is no conversion and a
cart holds items of one ISO 4217 currency only. Errors are fixed strings: 422
`invalid request` for any validation failure (unknown fields, wrong types and floats
included, and the input is never echoed), 404 `Not found`, 409 with one of
`Duplicate`, `Cart is not open`, `Item unavailable`, `Idempotency conflict`,
`Price changed`. Lists take `limit` 1..100 (default 100) and `after` (a UUID) and are
ordered by id.

| Method and path | Scope | Notes |
|---|---|---|
| `POST /v1/catalog/items` | `catalog:write` | `sku` (`[A-Za-z0-9._-]{1,64}`, unique per workspace, else 409), `name` (1..200, no control characters), `unit_price_minor` (0..10^10), `currency`. 201. |
| `GET /v1/catalog/items`, `GET /v1/catalog/items/{id}` | `catalog:read` | |
| `PATCH /v1/catalog/items/{id}` | `catalog:write` | Any of `name`, `unit_price_minor`, `active`. Placed orders keep their price. |
| `POST /v1/promotions` | `promotions:write` | `code` (`[A-Z0-9_-]{1,32}`, unique), `currency`, exactly one of `percent_off` (1..100) or `amount_off_minor`, optional `min_subtotal_minor`. 201. |
| `GET /v1/promotions` | `promotions:read` | |
| `POST /v1/carts` | `cart:write` | `{currency}`. 201 with the priced cart. |
| `GET /v1/carts/{id}` | `cart:read` | Priced at current catalog prices. |
| `PUT /v1/carts/{id}/lines/{item_id}` | `cart:write` | `{quantity}` 0..1000; 0 removes the line. Other currency 422, inactive item 409, at most 100 lines. |
| `PUT /v1/carts/{id}/promotion`, `DELETE /v1/carts/{id}/promotion` | `cart:write` | Attach a code (unknown 404) or detach it. |
| `POST /v1/orders` | `orders:write` | Header `Idempotency-Key` (`[A-Za-z0-9_.:-]{1,128}`, required). Body `cart_id`, optional `expected_total_minor`. 201 created, 200 replay. |
| `GET /v1/orders`, `GET /v1/orders/{id}` | `orders:read` | Order with its line snapshot. |
| `POST /v1/orders/{id}/cancel` | `orders:write` | `placed` to `cancelled`; repeating it returns the cancelled order. |

A priced cart or order carries `lines` (`item_id`, `sku`, `name`, `unit_price_minor`,
`quantity`, `line_total_minor`), `subtotal_minor`, `discount_minor`, `total_minor`,
`currency` and `promotion_code`; a cart also has `status` (`open`/`ordered`) and
`promotion_applied`; an order has `status`, `cart_id`, `created_at`, `cancelled_at`.

### Pricing rules (`pricing.quote`)

- `line_total = unit_price_minor × quantity`; `subtotal = Σ line_total`. Integers only;
  a float, a bool or an out-of-range number is rejected.
- A promotion applies only when it is active, has the cart's currency, and the subtotal
  is at least `min_subtotal_minor` (inclusive). Otherwise the cart shows the code with
  `promotion_applied: false` and no discount.
- Percent: `discount = subtotal × percent_off // 100` (rounded down to the minor
  unit). Amount: `discount = min(amount_off_minor, subtotal)`, so a total is never
  negative. One promotion per cart; no stacking.
- Lines are priced in SKU order, so the same cart always gives the same result.

### Order placement (duplicate order protection)

One transaction: an advisory lock on the workspace and key serializes requests for
that key; the cart row is then locked `FOR UPDATE`.

- Same key, same request (`cart_id`, `expected_total_minor`, SHA-256 fingerprint):
  the first order is returned with 200, even after a price change.
- Same key, different request: 409 `Idempotency conflict`.
- A cart becomes at most one order: once ordered it is `ordered` and further line,
  promotion or order changes are 409 `Cart is not open`; `UNIQUE(workspace_id, cart_id)`
  backs this up in the schema.
- With `expected_total_minor` (the total the buyer saw), a different current total
  is 409 `Price changed` and nothing is written. An empty cart is 422; a cart with a
  withdrawn item is 409 `Item unavailable`.
- The order copies each line's SKU, name, price and quantity, the discount and the
  applied code; later catalog edits do not change it.

## Migration gates (registry `commerce`)

| Gate | What this pilot shows | Still open |
|---|---|---|
| order state parity | Orders have two states, `placed` and `cancelled`, enforced by a CHECK; cancel is terminal and idempotent. | No legacy order source to compare: the registry source (`commerce-product-scraper`) is a scraper, not an order system. |
| payment boundary | No payment route or state; `paid`, `captured`, `refunded` fail the CHECK (test). | Calling `platform-payment` for an intent stays closed until D8 is reopened. |
| duplicate order protection | Concurrent replays of one key give one order; concurrent orders for one cart under different keys give one order; changed request is 409. | None for the pilot. |

## Verification record — 2026-10-29

Local: Python 3.12, PostgreSQL 16.2 via `pgserver`,
`PLATFORM_TEST_DSN="dbname=postgres user=postgres host=<socket dir>"`. Each test
gets its own throwaway database and a NOLOGIN NOSUPERUSER NOBYPASSRLS runtime role;
HTTP tests use real RS256 tokens. No external service is called.

RED, before each implementation:

- `runtime_tests/test_pricing.py`: collection error (no `pricing` module), then
  `25 failed` against a stub raising `NotImplementedError`. GREEN: `25 passed`.
- `runtime_tests/test_store.py`: `31 failed` against a stub store and empty
  migrations. GREEN after `migrations.py` and `store.py`: `31 passed`.
- `runtime_tests/test_http.py`: `25 failed` against a stub `create_app`. First run
  after `app.py`: 1 failure (a JSON `cart_id` string was rejected by strict UUID
  validation), fixed with a non-strict UUID field; then `25 passed`.
- `runtime_tests/test_lifecycle.py`: collection error (no `__main__`), then `3 passed`.

Mutation checks (each change made by hand, run, then reverted):

| Change | Result |
|---|---|
| Skip the fingerprint comparison | 2 failed (changed-request conflict, HTTP flow) |
| Drop the per-key advisory lock | concurrent replay test failed 3 of 3 runs |
| Skip the open-cart lock in `place_order` | 3 failed (one order per cart, empty/withdrawn cart, HTTP flow) |
| Readiness with one comma privilege list per table | 17 failed (per-privilege readiness cases) |

Final: `python -m pytest -q` `120 passed` (36 offline contract tests and 84 runtime
tests, no skips), one upstream Starlette/httpx deprecation warning. Without
`PLATFORM_TEST_DSN` the 57 database cases skip visibly and prove nothing about
durability. `bash scripts/check.sh` passes, `ruff check .` is clean, and a wheel builds.
CI on the pushed branch is recorded in the handoff, not here.

## Deliberate omissions

- Payment: no intent, capture, refund, ledger or `paid` state (D8).
- Inventory and stock reservation, tax, shipping (that is `platform-logistics`),
  customer accounts or addresses (`platform-identity`), multi-currency carts,
  promotion stacking, usage limits or expiry dates.
- Cart creation is not idempotent (a retry makes a second empty cart); only order
  placement takes an `Idempotency-Key`.
- No events or outbox: nothing tells other services that an order was placed.
- No retention or purge job; orders keep catalog names (no personal data is stored:
  the only person reference is the actor UUID in `placed_by`, not returned by the API).

## Rollback

The runtime has no consumers. Rollback stops the service. Do not downgrade applied
SQL or overwrite a live database; restore only into a new isolated database and check
synthetic workspace reads first.

## Staging plan (not executed)

Nothing below has been done; each step needs the owner's go. Earliest date
2026-11-01 (Neon `empire-platform` compute quota resets; Railway deploys stop at an
approval step).

1. Database: a dedicated database for this service, a DDL role for `migrate`, and a
   NOSUPERUSER NOBYPASSRLS runtime role with exactly the grants above. Connection
   strings go to Infisical `/platform-commerce`.
2. Image: build `wheelhouse/` (this wheel plus `platform-backend-core` at the CI-pinned
   commit and dependencies), deploy one Railway `serve` service with the JWT issuer
   `empire-platform`, run `migrate` once with the DDL role, approve the pending
   deployment.
3. Smoke test with a synthetic workspace token: `/readyz` 200; create an item, a
   promotion and a cart; `POST /v1/orders` twice with one key returns one order (201
   then 200); a second key for the same cart is 409; cancel returns `cancelled`.
4. Then Sentry and the uptime monitor; only after that pick a first consumer.
