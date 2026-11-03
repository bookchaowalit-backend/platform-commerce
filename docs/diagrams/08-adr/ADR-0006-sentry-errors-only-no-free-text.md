# ADR-0006: Sentry reports errors only and sends no free text

- Status: accepted (retro-documented 2026-11-03)

## Decision
`init_sentry()` ทำงานเมื่อมี `SENTRY_DSN` เท่านั้น; `traces_sample_rate=None`, `trace_propagation_targets=[]`, `send_default_pii=False`,
`include_local_variables=False`, `max_request_body_size="never"`, ปิด logging integration. `before_send` ลบ exception value,
message, logentry, breadcrumbs, extra, user, request (เหลือ method) และ dynamic sampling context. `CaptureErrors` เป็น middleware
ชั้นในสุดเพราะ core `_Boundary` กลืน exception เป็น 500 ก่อน Sentry integration ชั้นนอกจะเห็น.

## Evidence
- `src/platform_commerce/_sentry.py`, `src/platform_commerce/app.py` (`app.user_middleware.append(Middleware(CaptureErrors))`)
- `runtime_tests/test_sentry.py` (11 tests รวม `test_no_exception_text_leaves_the_process`)
- git: PR #2–#12 (2026-11-02/03), final `d9b26c2` "send no free text to Sentry (port security 0187719)"
- ops record: book-platforms-status (2026-11-03): commerce main `d678a5f` CLI-deployed, `sentry: enabled` logged

## Consequences
- Event มีแค่ type, stack, route template, tags, release — debug ต้องอาศัย stack line.
- Owner revert ได้ถ้าต้องการ message text (ops record).
