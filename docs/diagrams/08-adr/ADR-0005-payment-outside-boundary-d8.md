# ADR-0005: Payment stays outside the commerce boundary (owner decision D8)

- Status: accepted (retro-documented 2026-11-03)

## Decision
Order มีสองสถานะ `placed` และ `cancelled` เท่านั้น. ไม่มี payment intent, capture, refund, ledger หรือ route ที่เรียก `platform-payment`.
Boundary rule ระยะยาว: commerce ต้องเรียก Payment เพื่อสร้าง payment intent และห้ามสร้าง ledger entry เอง.

## Evidence
- `src/platform_commerce/migrations.py` (comment D8, `CHECK(status IN ('placed','cancelled'))`)
- `docs/runtime.md` ("Payment is out of scope (owner decision D8)", Migration gates table)
- `docs/CONTRACT-SURFACE.md` (Boundary rules)
- Tests: `runtime_tests/test_store.py::test_no_order_can_reach_a_payment_state`, `runtime_tests/test_http.py::test_payment_is_outside_this_boundary`

## Consequences
- Migration gate "payment boundary" เปิดค้างจนกว่า D8 ถูก reopen.
- `contract.json` `depends_on` มี `payment` แต่ runtime ไม่มี dependency จริง.
