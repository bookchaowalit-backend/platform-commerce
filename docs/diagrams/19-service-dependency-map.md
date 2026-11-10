# 19 — Service dependency map

```mermaid
flowchart TD
  API["commerce-api"]
  subgraph Runtime["Runtime dependencies (hard)"]
    NEON[("Neon Postgres platform-commerce")]
    JWKS["platform-identity JWKS"]
  end
  subgraph Soft["Runtime dependencies (soft)"]
    SEN["Sentry (no-op without DSN)"]
  end
  subgraph Host["Platform"]
    RW["Railway asia-southeast1 container + healthcheck"]
  end
  subgraph Build["Build-time"]
    CORE["platform-backend-core @21d5f44 (GitHub)"]
    PYPI["PyPI: fastapi via core, uvicorn, sentry-sdk, psycopg, pyjwt"]
    BASE["Docker Hub python:3.12-slim"]
  end
  subgraph Callers["Dependents"]
    HUB["Remote MCP hub cell"]
    UP["Uptime worker"]
  end
  subgraph Declared["Declared but not wired"]
    PAY["platform-payment (D8)"]
    OBS["observability (library, decision open)"]
  end
  HUB --> API
  UP --> API
  API --> NEON
  API --> JWKS
  API --> SEN
  RW --> API
  CORE --> API
  PYPI --> API
  BASE --> API
  API -.-> PAY
  API -.-> OBS
```

| Dependency | Kind | If down |
|---|---|---|
| Neon | hard | `/readyz` 503, data routes 500/504 |
| Identity JWKS | hard for auth | 401 on all `/v1` after key cache expires (≤ 60 s) |
| Sentry | soft | errors not reported; requests unaffected |
| Railway | host | service down |
| GitHub / PyPI / Docker Hub | build | cannot build new image |

Sources: `src/platform_commerce/__main__.py`, `src/platform_commerce/_sentry.py`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `contract.json`, `.railway/railway.ts`, `platform-backend-core@21d5f44` `auth.py`, `db.py`, ops record: book-platforms-status (2026-11-03)

## Open questions
- ไม่มี
