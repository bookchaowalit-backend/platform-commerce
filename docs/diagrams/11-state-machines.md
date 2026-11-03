# 11 — State machines

## Cart (`cart.status`)

```mermaid
stateDiagram-v2
  [*] --> open: POST /v1/carts
  open --> open: PUT line, PUT or DELETE promotion
  open --> ordered: POST /v1/orders succeeds
  ordered --> ordered: GET returns order snapshot; writes give 409 Cart is not open
```

## Order (`commerce_order.status`)

```mermaid
stateDiagram-v2
  [*] --> placed: POST /v1/orders (201)
  placed --> placed: same key same request (200 replay)
  placed --> cancelled: POST /v1/orders/{id}/cancel, sets cancelled_at
  cancelled --> cancelled: cancel again returns order unchanged
  cancelled --> [*]
```

CHECK constraint อนุญาตแค่ `placed`, `cancelled`; `paid`/`captured`/`refunded` ถูกปฏิเสธ (D8). `cancelled_at IS NOT NULL` เมื่อ cancelled เท่านั้น.

## Promotion (`active` + `ends_at`, ไม่มี status column)

```mermaid
stateDiagram-v2
  [*] --> live: POST /v1/promotions (active true, ends_at null)
  live --> withdrawn: PATCH active false
  withdrawn --> live: PATCH active true
  live --> expired: clock passes ends_at
  expired --> live: PATCH ends_at null or later
  live --> live: PATCH ends_at in future
```

"live" = `active AND (ends_at IS NULL OR ends_at > clock_timestamp())` (`LIVE_PROMOTION`). Cart ที่ถือ code ที่ไม่ live แสดง `promotion_applied: false`; `place_order` ตรวจซ้ำ.

## Catalog item (`active`)

```mermaid
stateDiagram-v2
  [*] --> active: POST /v1/catalog/items
  active --> inactive: PATCH active false
  inactive --> active: PATCH active true
```

Inactive item: `PUT line` = 409 `Item unavailable`; cart ที่มี item นี้สั่งไม่ได้ (409).

Sources: `src/platform_commerce/migrations.py`, `src/platform_commerce/store.py`, `src/platform_commerce/app.py`, `runtime_tests/test_store.py`

## Open questions
- ไม่มี
