# 21 — Incident response

ไม่มี RUNBOOK.md ใน repo. Flow นี้ประกอบจาก alert channel ที่มีจริง (uptime worker → Telegram, Sentry) และ rollback rule ใน `docs/runtime.md`.

```mermaid
flowchart TD
  A1["Uptime worker: commerce-api down after 2 failed hourly /readyz"] --> TG["Telegram alert"]
  A2["Sentry issue: unhandled exception, type + stack + route only"] --> SE["Sentry notification (rule unknown)"]
  A3["CI red on main (GitHub Actions)"] --> GH["GitHub notification"]
  TG --> T["Triage by owner or agent"]
  SE --> T
  GH --> T
  T --> Q1{"Readiness 503?"}
  Q1 -- yes --> R1["Check Neon quota or suspend, migration checksum, runtime grants, RLS"]
  Q1 -- no --> Q2{"401 on all calls?"}
  Q2 -- yes --> R2["Check identity JWKS, JWT_ISSUER, JWT_AUDIENCE"]
  Q2 -- no --> R3["Read Sentry stack line, reproduce with runtime_tests"]
  R1 --> F["Fix test-first on branch, PR, merge locally"]
  R2 --> F
  R3 --> F
  F --> D["railway up --ci from git archive main"]
  D --> V["Verify /readyz 200 and Telegram recovered message"]
  R1 -. "data damage" .-> RB["Rollback: stop service; restore only into a new isolated DB; check synthetic workspace reads"]
  V --> PM["Postmortem: no template or location in repo"]
```

ช่องทางและข้อเท็จจริง:
- Uptime: down = 2 consecutive failures; reminder ทุก 6 ชั่วโมง; ส่ง "recovered" เมื่อกลับมา (uptime worker `src/monitor.ts`).
- Sentry: errors only; message text ถูกตัด จึง triage จาก exception type + file/function/line.
- Startup failure: process exit ด้วยข้อความคงที่ `Service configuration or dependency unavailable` (ไม่บอก variable) → ดู Railway deploy status.
- Known cause ในอดีต: Neon `empire-platform` quota (ops record) — commerce ใช้ project ของตัวเองแล้ว.

Sources: `docs/runtime.md` ("Rollback", "Staging plan"), `src/platform_commerce/__main__.py`, `src/platform_commerce/_sentry.py`, `src/platform_commerce/store.py` (`ready`), `.github/workflows/check.yml`, `bookchaowalit/platform-uptime-worker@fe04d27` `src/monitor.ts`, `src/targets.ts`, ops record: book-platforms-status (2026-11-03)

## Open questions
- Severity levels, on-call, และที่เก็บ postmortem — ไม่ได้กำหนด.
- Rollback ของ code (redeploy commit ก่อนหน้า ด้วย `railway up` หรือ Railway rollback ของ deployment เดิม) — ยังไม่เขียนไว้.
