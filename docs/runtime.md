# Commerce runtime pilot

Status: implemented and locally verified; deployment artifacts staged only. No
production activation is claimed, and `contract.json` stays `scaffolded` (its guard
requires activation evidence). The pattern follows `platform-communication`
(main `b78809e`) and `platform-backend-core` at `88306b28`.

Scope is this repository's contract capabilities, kept deliberately small:
catalog items with integer minor-unit prices, carts, deterministic pricing with one
simple promotion per cart, and idempotent order placement. **Payment is out of
scope** (owner decision D8): there is no payment intent, capture, refund or ledger
code, and the database refuses any order status other than `placed` or `cancelled`.

## Installation and lifecycle

Python >=3.12, PostgreSQL >=16. `platform-backend-core==0.1.0` comes from the
reviewed commit CI pins (`88306b28228f`). Nothing is published to PyPI.
`railway.toml` is a reference release asset; no Railway deployment has been run.

### Container image

`docker build .` works from a clean checkout; no pre-staged `wheelhouse/` is
needed. The `Dockerfile` is two stages:

1. `build` (`python:3.12-slim` plus `git`): `pip wheel` builds this service's wheel
   and `platform-backend-core` from the same reviewed commit CI installs
   (`88306b28228f789eecd214a11ca8a0640e9d6233`), with all transitive dependencies.
2. `runtime` (`python:3.12-slim`, no git, no build tools): installs only those
   wheels with `--no-index`, runs as UID/GID `65532`, `PORT=8080`, and keeps
   `CMD ["python", "-m", "platform_commerce", "serve"]`. Run `migrate` as a
   separate one-off with the DDL-role DSN (same image, command override).

`.dockerignore` keeps `.git`, `.venv`, build output and `.env*` out of the build
context. CI job `image` in `shared-runtime.yml` runs `docker build` on every push
and pull request, then checks that the image imports the service, that
`python -m platform_commerce --help` runs, and that it runs as a non-root user. It
never pushes or deploys. `tests/test_build_hygiene.py` (part of `scripts/check.sh`)
fails if the Dockerfile copies a git-ignored path, stops being multi-stage, pins a
core commit other than the workflow's, runs the final stage as root or changes the
CMD, if CI stops building the image, or if any workflow `uses:` is not pinned to a
40-hex commit SHA (tags go in a trailing comment). Upgrading the core means changing
the commit in the workflow, the Dockerfile and `[tool.uv.sources]` together; the
tests fail on any mismatch.

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
| `promotion` | SELECT, INSERT, UPDATE |
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
`Price changed`. Only request validation and the store's `InvalidInput` map to 422;
any other exception (a plain `ValueError` from a server bug included) is the core's
redacted 500 `internal server error`. Lists take `limit` 1..100 (default 100) and `after` (a UUID) and are
ordered by id.

| Method and path | Scope | Notes |
|---|---|---|
| `POST /v1/catalog/items` | `catalog:write` | `sku` (`[A-Za-z0-9._-]{1,64}`, unique per workspace, else 409), `name` (1..200, no control characters), `unit_price_minor` (0..10^10), `currency`. 201. |
| `GET /v1/catalog/items`, `GET /v1/catalog/items/{id}` | `catalog:read` | |
| `PATCH /v1/catalog/items/{id}` | `catalog:write` | Any of `name`, `unit_price_minor`, `active`. Placed orders keep their price. |
| `POST /v1/promotions` | `promotions:write` | `code` (`[A-Z0-9_-]{1,32}`, unique), `currency`, exactly one of `percent_off` (1..100) or `amount_off_minor`, optional `min_subtotal_minor`. 201. |
| `PATCH /v1/promotions/{id}` | `promotions:write` | Any of `active` (bool) or `ends_at` (RFC 3339 with an offset, or `null` to clear). An empty body, a naive timestamp or `active: null` is 422. Carts carrying the code price without it from then on. |
| `GET /v1/promotions` | `promotions:read` | Each promotion includes `active` and `ends_at`. |
| `POST /v1/carts` | `cart:write` | `{currency}`. 201 with the priced cart. |
| `GET /v1/carts/{id}` | `cart:read` | An `open` cart is priced at current catalog prices with `order_id: null`. An `ordered` cart returns its order's snapshot (`order_id`, lines, subtotal, discount, total), so it always matches `GET /v1/orders/{order_id}`. |
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
- A promotion applies only when it is active, not past its `ends_at` (database
  `clock_timestamp()`), has the cart's currency, and the subtotal
  is at least `min_subtotal_minor` (inclusive). Otherwise the cart shows the code with
  `promotion_applied: false` and no discount.
- Percent: `discount = subtotal × percent_off // 100` (rounded down to the minor
  unit). Amount: `discount = min(amount_off_minor, subtotal)`, so a total is never
  negative. One promotion per cart; no stacking.
- Lines are priced in SKU order, so the same cart always gives the same result.

### Order placement (duplicate order protection)

One transaction: an advisory lock on the workspace and key serializes requests for
that key; the cart row is then locked `FOR UPDATE`, and the priced `catalog_item` rows
(in id order) and the cart's `promotion` row `FOR SHARE`, so a concurrent price,
availability or promotion change waits until the order commits and the order matches
the catalog state it was priced from. The promotion is re-checked here: one withdrawn
or expired since the buyer's quote gives no discount (or 409 `Price changed` with
`expected_total_minor`).

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

## Review follow-ups — 2026-10-29 (branch `commerce-followups`)

Four low-severity review findings on main `5f42c4b`, fixed test-first on the same
local setup (Python 3.12, PostgreSQL 16.2 via `pgserver`).

| Finding | Change |
|---|---|
| C1 a promotion could never be withdrawn (no route; runtime role lacked UPDATE) | Migration `0002` adds `promotion.ends_at`; `PATCH /v1/promotions/{id}` (`promotions:write`) sets `active` and/or `ends_at`; pricing treats a withdrawn or expired promotion as not applied, `place_order` re-checks it; `promotion` UPDATE is a required runtime grant checked by readiness. |
| C2 `GET` of an `ordered` cart repriced from the live catalog | An ordered cart returns its order snapshot and `order_id`; every cart carries `order_id`. |
| C3 catalog rows were not locked while an order was priced | `place_order` share-locks the priced `catalog_item` rows and the promotion row. |
| C4 every `ValueError` became 422, hiding server bugs | `store.InvalidInput(ValueError)` for client input; only it maps to 422, everything else is a redacted 500. |

RED (new tests, before any implementation): `20 failed, 84 passed` in
`runtime_tests` — `update_promotion` missing (C1, 9 cases incl. the
least-privilege grant test), `KeyError: 'order_id'` (C2), the lock probe saw both
concurrent writes commit, `{'item': False, 'promotion': False}` (C3), a server-side
`ValueError` answered 422 and store validation raised plain `ValueError` (C4, 9 cases).

GREEN: `python -m pytest -q` `141 passed` (36 offline, 105 runtime: the 20 new tests
plus one new readiness case for `promotion` UPDATE), `ruff check .` clean,
`bash scripts/check.sh` passes.

Mutation checks (each reverted):

| Change | Result |
|---|---|
| Drop `FOR SHARE OF i` on catalog rows | lock test failed |
| Drop `FOR SHARE` on the promotion row | lock test failed |
| Ignore `ends_at` in pricing | 3 failed (store expiry, order re-check, HTTP PATCH) |
| Reprice ordered carts again | 3 failed (snapshot, least-privilege flow, HTTP PATCH) |
| Remove `promotion` UPDATE from readiness | least-privilege grant test failed |

Staging note: an existing runtime role needs `GRANT UPDATE ON promotion` before this
version is ready (readiness reports 503 until then), and `migrate` must apply `0002`.

## Build hygiene — 2026-10-29 (branch `build-hygiene`)

Ported from `platform-developer` `8047108`. Two low-severity findings on main `a933cf6`:

1. `check.yml` and `shared-runtime.yml` used `actions/checkout@v4` and
   `actions/setup-python@v5` by tag. Both are pinned to commit SHAs (`11d5960a...` =
   v4, `a26af69b...` = v5, lightweight tags resolved with `gh api .../git/ref/tags/...`),
   tag in a comment.
2. The `Dockerfile` copied the git-ignored `wheelhouse/`, so it could not build from a
   clone. It is now the multi-stage build under "Container image", and CI builds it.

RED (`tests/test_build_hygiene.py` written first, run on the old files):
`python3 -m unittest tests.test_build_hygiene` 5 of 7 failed (unpinned actions in
`check.yml` and `shared-runtime.yml`; `wheelhouse` in the Dockerfile; one `FROM`; no
core commit in the Dockerfile; no `docker build` step). The checker self-test and the
existing non-root `USER` passed.

GREEN: `bash scripts/check.sh` and `ruff check .` pass; the image build is verified
only by the CI `image` job (no local Docker). Nothing was pushed to a registry or
deployed.

## Deliberate omissions

- Payment: no intent, capture, refund, ledger or `paid` state (D8).
- Inventory and stock reservation, tax, shipping (that is `platform-logistics`),
  customer accounts or addresses (`platform-identity`), multi-currency carts,
  promotion stacking, usage limits or start dates.
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
2. Image: `docker build .` (see "Container image"; CI already builds it on every
   push), deploy one Railway `serve` service with the JWT issuer
   `empire-platform`, run `migrate` once with the DDL role, approve the pending
   deployment.
3. Smoke test with a synthetic workspace token: `/readyz` 200; create an item, a
   promotion and a cart; `POST /v1/orders` twice with one key returns one order (201
   then 200); a second key for the same cart is 409; cancel returns `cancelled`.
4. Then Sentry and the uptime monitor; only after that pick a first consumer.
