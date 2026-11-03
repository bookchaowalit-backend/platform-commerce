# 09 — ERD

Schema จาก `MIGRATIONS` (namespace `commerce`, versions `0001`, `0002`). ทุก PK/FK เป็น composite ที่ขึ้นต้นด้วย `workspace_id`.

```mermaid
erDiagram
  catalog_item ||--o{ cart_line : "item_id"
  cart ||--o{ cart_line : "cart_id"
  cart ||--o| commerce_order : "cart_id UNIQUE"
  commerce_order ||--|{ order_line : "order_id"
  promotion |o--o{ cart : "code = promotion_code (no FK)"
  catalog_item {
    uuid workspace_id PK
    uuid id PK
    text sku "UNIQUE per workspace, [A-Za-z0-9._-]{1,64}"
    text name "1..200"
    bigint unit_price_minor "0..10^10"
    text currency "[A-Z]{3}"
    boolean active "default true"
    timestamptz created_at
    timestamptz updated_at
  }
  promotion {
    uuid workspace_id PK
    uuid id PK
    text code "UNIQUE per workspace, [A-Z0-9_-]{1,32}"
    text currency
    integer percent_off "1..100, xor amount_off_minor"
    bigint amount_off_minor "1..10^10"
    bigint min_subtotal_minor "default 0"
    boolean active "default true"
    timestamptz ends_at "0002, nullable"
    timestamptz created_at
  }
  cart {
    uuid workspace_id PK
    uuid id PK
    text currency
    text status "open or ordered"
    text promotion_code "nullable"
    timestamptz created_at
    timestamptz updated_at
  }
  cart_line {
    uuid workspace_id PK
    uuid cart_id PK
    uuid item_id PK
    integer quantity "1..1000"
  }
  commerce_order {
    uuid workspace_id PK
    uuid id PK
    uuid cart_id "UNIQUE per workspace"
    text idempotency_key "UNIQUE per workspace"
    text fingerprint "SHA-256"
    text status "placed or cancelled"
    text currency
    bigint subtotal_minor
    bigint discount_minor "0..subtotal"
    bigint total_minor "= subtotal - discount"
    text promotion_code "applied code or null"
    uuid placed_by "JWT sub, not returned by API"
    timestamptz created_at
    timestamptz cancelled_at "set iff cancelled"
  }
  order_line {
    uuid workspace_id PK
    uuid order_id PK
    uuid item_id PK "snapshot, no FK to catalog_item"
    text sku
    text name
    bigint unit_price_minor
    integer quantity
    bigint line_total_minor "= unit_price * quantity"
  }
  platform_schema_migrations {
    text namespace PK
    text version PK
    text checksum "SHA-256 of SQL"
    timestamptz applied_at
  }
```

## RLS และ runtime role
- ทั้ง 6 ตาราง (`TABLES`) มี `ENABLE` + `FORCE ROW LEVEL SECURITY` และ policy `workspace` (`USING` + `WITH CHECK` บน `app.workspace_id`).
- `platform_schema_migrations` สร้างโดย core `MigrationRunner` (ใช้ร่วมทุก namespace ใน DB เดียว) ไม่มี RLS; runtime role ต้องมีแค่ `SELECT`.
- Index เพิ่ม: `commerce_order(workspace_id, created_at, id)`.
- Runtime grants (readiness ตรวจทีละรายการ): `catalog_item`, `promotion`, `cart` = SELECT/INSERT/UPDATE; `cart_line` = +DELETE;
  `commerce_order` = SELECT/INSERT/UPDATE; `order_line` = SELECT/INSERT. ไม่มี DELETE บน order ใดๆ.
- Personal data: เก็บแค่ `placed_by` (actor UUID); ไม่มีชื่อ/อีเมล/ที่อยู่.

Sources: `src/platform_commerce/migrations.py`, `src/platform_commerce/store.py` (`REQUIRED_PRIVILEGES`, `ready`), `docs/runtime.md`, `platform-backend-core@21d5f44` `migrations.py`

## Open questions
- Retention ของ cart ที่ไม่ได้สั่ง และ order/idempotency key — ไม่มี purge job (runtime.md "Deliberate omissions").
