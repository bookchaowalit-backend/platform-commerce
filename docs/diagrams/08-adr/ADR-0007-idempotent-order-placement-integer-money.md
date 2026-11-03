# ADR-0007: Integer minor-unit money and idempotent order placement

- Status: accepted (retro-documented 2026-11-03)

## Decision
- เงินเป็น integer minor unit ของ ISO 4217 currency เดียวต่อ cart; float/bool ถูกปฏิเสธ; percent discount ปัดลง; amount discount cap ที่ subtotal.
- `POST /v1/orders` ต้องมี `Idempotency-Key` (`[A-Za-z0-9_.:-]{1,128}`); fingerprint = SHA-256 ของ `[cart_id, expected_total_minor]`.
  Same key + same request = 200 replay; different request = 409; cart หนึ่งเป็น order ได้ครั้งเดียว (`UNIQUE(workspace_id,cart_id)`).
- Serialization: `pg_advisory_xact_lock` ต่อ (workspace, key), cart `FOR UPDATE`, catalog rows และ promotion `FOR SHARE`.

## Evidence
- `src/platform_commerce/pricing.py`, `src/platform_commerce/store.py` (`place_order`, `order_fingerprint`, `_priced_cart(for_order=True)`)
- `src/platform_commerce/migrations.py` (UNIQUE constraints, CHECK `total_minor = subtotal_minor - discount_minor`)
- `runtime_tests/test_pricing.py`, `runtime_tests/test_store.py::test_concurrent_replays_of_one_key_create_one_order`, `test_place_order_locks_the_rows_it_prices`
- `docs/runtime.md` ("Order placement", mutation checks)

## Consequences
- Idempotency key เก็บถาวรใน `commerce_order` (ไม่มี expiry/purge).
- Cart creation ไม่ idempotent.
