# 03 — User flows (API call flows per caller)

ไม่มี UI; flow = ลำดับ API call ต่อ caller. ทุก call ต้องมี `Authorization: Bearer <RS256 JWT>`; ไม่มี token = 401, ไม่มี scope = 403.

## Flow A — Catalog manager ตั้งค่า catalog และ promotion

```mermaid
flowchart TD
  A0["Token with catalog:write + promotions:write"] --> A1["POST /v1/catalog/items"]
  A1 -->|201| A2["Item active"]
  A1 -->|"409 Duplicate (sku exists)"| A1x["Use existing item: GET /v1/catalog/items"]
  A1 -->|"422 invalid request"| A1e["Fix input"]
  A2 --> A3["PATCH /v1/catalog/items/{id}: price or active=false"]
  A0 --> P1["POST /v1/promotions"]
  P1 -->|201| P2["Promotion active"]
  P1 -->|"409 Duplicate code"| P1x["GET /v1/promotions"]
  P2 --> P3["PATCH /v1/promotions/{id}: active=false or ends_at"]
  P3 --> P4["Carts carrying the code price without it"]
```

## Flow B — Buyer / agent checkout

```mermaid
flowchart TD
  B0["Token with cart:write, cart:read, orders:write"] --> B1["POST /v1/carts {currency}"]
  B1 -->|"201 priced empty cart"| B2["PUT /v1/carts/{id}/lines/{item_id} {quantity}"]
  B2 -->|"422 other currency or >100 lines"| B2e["Fix line"]
  B2 -->|"409 Item unavailable"| B2e
  B2 --> B3{"Promotion?"}
  B3 -- yes --> B4["PUT /v1/carts/{id}/promotion {code}"]
  B4 -->|"404 unknown code"| B3
  B3 -- no --> B5["GET /v1/carts/{id}: read total_minor"]
  B4 --> B5
  B5 --> B6["POST /v1/orders, Idempotency-Key, cart_id, expected_total_minor"]
  B6 -->|"201 created"| B7["Order placed; cart becomes ordered"]
  B6 -->|"200 same key same request"| B7
  B6 -->|"409 Price changed"| B5
  B6 -->|"409 Idempotency conflict"| B6e["New key or same request"]
  B6 -->|"409 Cart is not open"| B6f["GET /v1/carts/{id} returns order_id"]
  B6 -->|"422 Empty cart"| B2
  B7 --> B8["POST /v1/orders/{id}/cancel (repeat returns cancelled)"]
```

## Flow C — Probes และ operator

```mermaid
flowchart LR
  U["Uptime worker hourly"] --> R["GET /readyz"]
  RW["Railway healthcheck"] --> R
  R --> R1{"DB ping, migration checksums, forced RLS on 6 tables, 18 grants"}
  R1 -- all true --> R2["200 ready"]
  R1 -- any false --> R3["503 unavailable"]
  O["Operator"] --> M["python -m platform_commerce migrate (DDL DSN)"]
  M --> S["python -m platform_commerce serve (runtime DSN)"]
```

Sources: `src/platform_commerce/app.py`, `src/platform_commerce/store.py`, `src/platform_commerce/__main__.py`, `railway.toml`, `docs/runtime.md`, `runtime_tests/test_http.py`, `platform-backend-core@21d5f44` `platform_backend_core/http.py`, ops record: book-platforms-status (2026-11-03)

## Open questions
- Caller จริงที่เดิน Flow B วันนี้มีแค่ MCP hub (owner) — ยังไม่มี app consumer; flow ของ consumer ในอนาคตยังไม่ได้ออกแบบ.
- `POST /v1/carts` ไม่ idempotent (retry = cart ใหม่) — ยอมรับได้หรือควรมี key?
