# ADR-0004: Railway serverless container + own Neon project; deploy by Railway CLI

- Status: accepted (retro-documented 2026-11-03)

## Decision
- Host: Railway project `platform-commerce`, service `commerce-api`, region `asia-southeast1-eqsg3a`, sleep on (serverless),
  URL `https://commerce-api-production-9b24.up.railway.app`. Owner approved serverless for all new services 2026-10-29.
- DB: Neon free project `platform-commerce` (free quota per project). Secrets: Infisical `/platform-commerce` + Railway variables.
- Build: `railway.toml` `builder = "DOCKERFILE"`, `healthcheckPath = "/readyz"`, timeout 30 s, restart ON_FAILURE max 3.
- Deploy: `railway up --ci` จาก `git archive` ของ main (ไม่มี GitHub source link, ไม่มี deploy job ใน Actions).

## Evidence
- `railway.toml`, `Dockerfile`, `PRODUCT.md` (Operating Context)
- ops record: book-platforms-status (2026-11-03) — "Live" list และ "Deploy recipe"
- Railway GraphQL `deployments` (read 2026-11-03): ทุก deployment `reason: deploy|redeploy`, ไม่มี `commitHash`, `cliMessage` เช่น `sentry hardening port src-commerce-d678a5f`
- Core pool defaults สำหรับ Neon resume (`platform-backend-core@21d5f44` `db.py`: timeout 20 s, connect 15 s, `check_connection`)

## Consequences
- Cold start หลัง sleep + Neon resume ~6–9 s (ops record); `/readyz` warm ~0.4 s.
- Git ไม่บอกว่า commit ไหน live; ต้องดู `cliMessage` ใน Railway (ดู 22-dora).
- `docs/runtime.md` ยังเขียนว่า "no Railway deployment has been run" — ล้าสมัย.
