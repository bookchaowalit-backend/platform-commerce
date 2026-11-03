# ADR-0002: PostgreSQL with forced row-level security per workspace; least-privilege runtime role

- Status: accepted (retro-documented 2026-11-03)

## Decision
- ทุกตารางมี `workspace_id` ใน primary key และ `ENABLE` + `FORCE ROW LEVEL SECURITY` พร้อม policy `workspace`
  (`USING` + `WITH CHECK` = `current_setting('app.workspace_id')`).
- Workspace มาจาก JWT claim `ws` เท่านั้น; `Database.transaction(workspace)` ตั้ง `app.workspace_id` แบบ `set_config(..., true)` ต่อ transaction.
- API ใช้ runtime role ที่เป็น NOSUPERUSER NOBYPASSRLS (core `_configure` ปฏิเสธ role ที่ privileged) และมี grant ครบ 18 รายการตาม `REQUIRED_PRIVILEGES`.
- Migration รันด้วย DDL role ผ่าน CLI `migrate` เท่านั้น; readiness เทียบ checksum ของ migration ที่ apply แล้ว.

## Evidence
- `src/platform_commerce/migrations.py` (`_rls`, `TABLES`, `MIGRATIONS` 0001/0002)
- `src/platform_commerce/store.py` (`REQUIRED_PRIVILEGES`, `ready`)
- `src/platform_commerce/__main__.py` (`migrate` vs `serve`)
- `platform-backend-core@21d5f44` `db.py`, `migrations.py`
- Tests: `runtime_tests/test_store.py::test_forced_rls_rejects_writes_for_another_workspace`, `test_documented_runtime_grants_are_sufficient`, `test_ready_requires_current_schema`

## Consequences
- ลืม `GRANT` ใหม่ = `/readyz` 503 (ตั้งใจ, fail closed).
- ห้ามแก้ migration ที่ apply แล้ว (checksum drift) — ต้องเพิ่ม version ใหม่.
