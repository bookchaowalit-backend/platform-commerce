# 15 — CI/CD pipeline

ทุก workflow trigger บน `push` (ทุก branch), `pull_request`, `workflow_dispatch`; `permissions: contents: read`; concurrency ต่อ ref
(cancel-in-progress). รันบน GitHub-hosted runners (public repo). **ไม่มี deploy job** — deploy เป็น Railway CLI แยก (ดู 18).

```mermaid
flowchart TD
  T["push / pull_request / workflow_dispatch"] --> CHK
  T --> SR
  subgraph CHK["check.yml (Check)"]
    C1["contract: matrix Python 3.11, 3.12"] --> C1a["check_schema_pin.py"] --> C1b["scripts/check.sh: check.py, schema pin, unittest tests/"]
    C2["python: reusable ci-python.yml v1.1.1 (87dc5e1c)"] --> C2a["uv sync --frozen --all-extras"] --> C2b["Start PostgreSQL"] --> C2c["Ruff lint"] --> C2d["mypy"] --> C2e["pytest -q --cov (PLATFORM_TEST_DSN)"] --> C2f["Coverage gate 94"] --> C2g["uv build --wheel"]
    C3["security: reusable security.yml v1.1.1"] --> C3a["gitleaks"]
    C3 --> C3b["semgrep"]
    C3 --> C3c["osv-scanner"]
    C3 --> C3d["trivy-fs"]
  end
  subgraph SR["shared-runtime.yml (Shared runtime)"]
    S1["image: docker build --pull, no push"] --> S2["import platform_backend_core and app"] --> S3["python -m platform_commerce --help"] --> S4["id -u is not 0"]
  end
  CHK --> G{"All green?"}
  SR --> G
  G -- "merge locally, push main" --> M["main"]
  M -. "manual: railway up --ci from git archive" .-> D["Railway commerce-api"]
```

Jobs ไม่มี `needs:` ระหว่างกัน (ขนานทั้งหมด). Coverage threshold "94" (measured 94.30% 2026-11-03, ratchet ตาม ADR-0004 TDD/SDD).

Run history 2026-10-01 → 2026-11-03 (`gh run list`): Check บน main 21 success / 2 failure (both 2026-10-13, `1a75145`, `86096a6`);
Shared runtime บน main 18 success.

Sources: `.github/workflows/check.yml`, `.github/workflows/shared-runtime.yml`, `bookchaowalit/platform-ci-workflows@87dc5e1c` `.github/workflows/ci-python.yml` + `security.yml`, `scripts/check.sh`, `pyproject.toml`, `tests/test_build_hygiene.py`, `gh run list -R bookchaowalit-backend/platform-commerce --limit 200 --json workflowName,headBranch,event,conclusion,createdAt,headSha` (2026-11-03). Central: [ADR-0004 TDD/SDD](https://github.com/bookchaowalit/architecture-docs/blob/main/docs/architecture/decisions/ADR-0004-tdd-sdd-standard.md)

## Open questions
- `scripts/check_registry_alignment.py` ไม่อยู่ใน CI (ต้องมี solo-empire checkout) — ควรเพิ่มไหม?
- `format-check: false` (follow-up: adopt ruff format) ยังค้าง.
