# Core 22 SDLC Diagram Pack — platform-commerce (commerce-api)

ชุด 22 visual ตาม SDLC Diagram Catalog v2 (knowledge-base `knowledge/tech/core-cs/sdlc-diagram-catalog.md`) วาดจาก code และ config
ที่ `origin/main` **fa79d31** (2026-11-03); runtime ที่ live คือ **d678a5f** (Railway CLI deploy 2026-11-03 04:23 UTC).
Live: https://commerce-api-production-9b24.up.railway.app (`/readyz` 200 ตรวจ 2026-11-03). ทุกภาพมี `Sources:`; สิ่งที่ไม่รู้อยู่ใน "Open questions".

แหล่งนอก repo ที่อ้าง: `platform-backend-core@21d5f44` (commit ที่ `pyproject.toml`/`uv.lock`/`Dockerfile` pin; อ่านจาก package ที่ติดตั้ง),
`bookchaowalit/platform-ci-workflows@87dc5e1c` (reusable workflows ที่ `check.yml` เรียก), `bookchaowalit/platform-uptime-worker@fe04d27`,
Railway GraphQL `deployments` (read-only), `gh` CLI, และ ops record: book-platforms-status (2026-11-03).
Central architecture-docs ไม่มีส่วนของ commerce (C4/ERD/flows); ลิงก์ ADR-0002 และ ADR-0004 ส่วนกลางในไฟล์ 14/15.
Reuse: [`docs/runtime.md`](../runtime.md) (API, pricing, order placement, rollback), [`docs/CONTRACT-SURFACE.md`](../CONTRACT-SURFACE.md), [`PRODUCT.md`](../../PRODUCT.md).

| # | Item | Status | File | Sources read |
|---|---|---|---|---|
| 1 | Business process (As-Is / To-Be) | done | [01-business-process.md](01-business-process.md) | `app.py`, `store.py`, `pricing.py`, `migrations.py`, `PRODUCT.md`, `docs/UPGRADE-PLAN.md`, `docs/CONTRACT-SURFACE.md`, `docs/runtime.md` |
| 2 | Use cases (scopes as actors) | done | [02-use-cases.md](02-use-cases.md) | `app.py`, `__main__.py`, core `auth.py`/`http.py`, ops record |
| 3 | User flows (API call flows) | done | [03-user-flows.md](03-user-flows.md) | `app.py`, `store.py`, `railway.toml`, `runtime_tests/test_http.py` |
| 4 | Traceability (RTM) | done (no specs/, IDs local) | [04-traceability.md](04-traceability.md) | `PRODUCT.md`, `docs/*.md`, `src/**`, `tests/**`, `runtime_tests/**`, workflows |
| 5 | C4 Context | done | [05-c4-context.md](05-c4-context.md) | `contract.json`, `__main__.py`, `_sentry.py`, `railway.toml`, ops record |
| 6 | C4 Container | done | [06-c4-container.md](06-c4-container.md) | `Dockerfile`, `railway.toml`, `pyproject.toml`, `__main__.py`, core `db.py`/`http.py` |
| 7 | C4 Component | done | [07-c4-component.md](07-c4-component.md) | `app.py`, `store.py`, `pricing.py`, `_sentry.py`, core `auth.py`/`http.py`/`db.py` |
| 8 | ADRs | done (7 retro ADRs) | [08-adr/](08-adr/) | see each ADR "Evidence" |
| 9 | ERD | done (with RLS + grants) | [09-erd.md](09-erd.md) | `migrations.py`, `store.py`, core `migrations.py` |
| 10 | Sequences | done (3) | [10-sequences.md](10-sequences.md) | `app.py`, `store.py`, core `http.py`/`auth.py`/`db.py` |
| 11 | State machines | done (4) | [11-state-machines.md](11-state-machines.md) | `migrations.py`, `store.py`, `app.py` |
| 12 | API and integrations | done (reuses `docs/runtime.md` § API) | [12-api-integration.md](12-api-integration.md) | `app.py`, `store.py`, core `http.py`/`auth.py`/`db.py`, live curl |
| 13 | Threat model (DFD + STRIDE) | done | [13-threat-model.md](13-threat-model.md) | `src/**`, `Dockerfile`, `.dockerignore`, `pyproject.toml`, core, shared `security.yml`, live curl |
| 14 | Backup / DR | done (no backup in repo; RTO/RPO not defined) | [14-backup-dr.md](14-backup-dr.md) | `docs/runtime.md`, `migrations.py`, workflows, ops record |
| 15 | CI/CD pipeline | done | [15-cicd-pipeline.md](15-cicd-pipeline.md) | `check.yml`, `shared-runtime.yml`, shared `ci-python.yml`/`security.yml`, `gh run list` |
| 16 | Deployment | done | [16-deployment.md](16-deployment.md) | `railway.toml`, `Dockerfile`, `__main__.py`, `_sentry.py`, Railway GraphQL, ops record |
| 17 | Test coverage matrix | done | [17-test-coverage-matrix.md](17-test-coverage-matrix.md) | `tests/*.py`, `runtime_tests/*.py`, `check.yml`, `docs/runtime.md` |
| 18 | Git / release workflow | done | [18-git-release-workflow.md](18-git-release-workflow.md) | `git log`, `gh pr list`, branch protection + rulesets API, Railway GraphQL |
| 19 | Service dependency map | done | [19-service-dependency-map.md](19-service-dependency-map.md) | `__main__.py`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `contract.json` |
| 20 | Observability | done | [20-observability.md](20-observability.md) | `_sentry.py`, `app.py`, core `http.py`, uptime worker `targets.ts`/`monitor.ts`/`worker.ts` |
| 21 | Incident response | done (no RUNBOOK in repo) | [21-incident-response.md](21-incident-response.md) | `docs/runtime.md`, `__main__.py`, `store.py`, uptime worker `monitor.ts` |
| 22 | DORA | done (2 of 5 computed, 3 not computable + proxies) | [22-dora.md](22-dora.md) | Railway GraphQL, `gh pr view`, `gh run list`, `git log` |

## Headline findings

1. **Docs ล้าสมัยเรื่อง deploy**: README ("Runtime pilot ... not deployed"), `docs/runtime.md` ("no Railway deployment has been run") และ CONTRACT-SURFACE ("not deployed") ขัดกับความจริง: live บน Railway ตั้งแต่ 2026-10-29 (19 deployments). `PRODUCT.md` ถูกต้องแล้ว.
2. **Legacy source path ไม่ตรงกัน**: `contract.json` ชี้ `.../commerce-product-scraper` แต่ README, CONTRACT-SURFACE และ UPGRADE-PLAN ชี้ `.../book-ecommerce-scraping`.
3. **Deploy ไม่ถูก gate โดย CI**: ไม่มี branch protection/rulesets บน main และ deploy เป็น CLI ~3 นาทีหลัง merge; Git ไม่บอกว่า commit ไหน live (ต้องอ่าน `cliMessage`).
4. **ไม่มี backup/restore ที่พิสูจน์ได้** สำหรับ Neon `platform-commerce`; RTO/RPO ไม่ได้กำหนด (ผลกระทบต่ำเพราะยังไม่มี consumer).
5. **`/metrics` ไม่ต้องใช้ token** และ direct Railway URL เปิดสาธารณะ (auth ยังบังคับที่ `/v1`); ไม่มี audit trail ของการแก้ราคา/promotion.
6. Dockerfile ใช้ `pip wheel` ตาม range ใน `pyproject.toml` ไม่ใช่ `uv.lock` — image อาจได้ dependency version ต่างจากที่ CI ทดสอบ.

## Validation

`node ~/work/core22/tools/validate.mjs docs/diagrams/*.md docs/diagrams/08-adr/*.md` → all mermaid blocks parse.
