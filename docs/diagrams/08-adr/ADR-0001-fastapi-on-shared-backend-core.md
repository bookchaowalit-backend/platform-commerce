# ADR-0001: FastAPI service on the shared platform-backend-core, pinned by commit

- Status: accepted (retro-documented 2026-11-03)
- Context: platform services each own their code but share a reviewed runtime core (HTTP boundary, auth, DB pool, migrations).

## Decision
commerce-api เป็น FastAPI app ที่สร้างจาก `platform_backend_core.create_app('commerce', ...)` และ core ถูก pin ที่ commit
`21d5f44d26220080cbed43b9807979dc84a8533a` พร้อมกันใน 3 ที่ (`pyproject.toml` `[tool.uv.sources]`, `uv.lock`, `Dockerfile`).
ไม่ publish ขึ้น PyPI; pin ด้วย Git commit เพื่อกัน dependency confusion.

## Evidence
- `src/platform_commerce/app.py` (`from platform_backend_core import create_app as base_app, require_scope`)
- `pyproject.toml` (`platform-backend-core==0.1.0`, `[tool.uv.sources]` rev), `Dockerfile` (`pip wheel ... @21d5f44d...`)
- `tests/test_build_hygiene.py::test_core_comes_from_the_ci_pinned_commit`
- `docs/runtime.md` ("Installation and lifecycle", "Container image")

## Consequences
- อัปเกรด core ต้องเปลี่ยน 3 ที่พร้อมกัน; test fail ถ้าไม่ตรง.
- Probe routes, body limit, timeout, redacted 500 และ metrics มาจาก core ไม่ได้อยู่ใน repo นี้.
- Core ไม่มี `py.typed`; mypy ใช้ `follow_untyped_imports`.
