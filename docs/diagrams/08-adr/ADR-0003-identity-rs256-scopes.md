# ADR-0003: Trust platform-identity RS256 tokens; authorize per route by scope

- Status: accepted (retro-documented 2026-11-03)

## Decision
- `TokenVerifier(issuer=JWT_ISSUER, audience=JWT_AUDIENCE, public_key | jwks_url)` — ต้องตั้งอย่างใดอย่างหนึ่งเท่านั้น.
- Production: issuer platform-identity (`https://identity-api-production-fad1.up.railway.app`), JWKS `/.well-known/jwks.json`, audience `commerce-api` (owner decision 2026-10-29; ops record).
- Token ต้องมี `sub`, `ws`, `iat`, `exp`, `jti`, `iss`, `aud`; อายุ ≤ 3600 s; ห้ามมี `del`/`obo`.
- แต่ละ route มี scope เดียว: `catalog:*`, `promotions:*`, `cart:*`, `orders:*` (read/write).

## Evidence
- `src/platform_commerce/__main__.py`, `src/platform_commerce/app.py` (`require_scope(...)` ทุก route)
- `platform-backend-core@21d5f44` `auth.py` (`TokenVerifier`, `_JWKS`), `http.py` (`require_scope`)
- `runtime_tests/test_http.py::test_scopes_tokens_and_workspaces_are_enforced`
- ops record: book-platforms-status (2026-11-03) — "JWT" และ "Identity activated" bullets

## Consequences
- ไม่มี revocation หรือ delegation check (core comment: "Shared services cannot enforce delegation status or revocation"); พึ่งอายุ token สั้น.
- Service ไม่แยก person กับ service client.
