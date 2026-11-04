# 05 — C4 Context

```mermaid
C4Context
  title System Context - platform-commerce (commerce-api)
  Person(owner, "Owner", "Runs migrate and CLI deploys, uses MCP tools")
  System_Ext(hub, "Remote MCP hub", "Cell platform-commerce, identity service client mcp-hub")
  System_Ext(gw, "Edge API gateway", "gateway.bookchaowalit.com, route /v1/platform-commerce")
  System(commerce, "commerce-api", "Catalog, cart, pricing, promotion, order per workspace")
  System_Ext(identity, "platform-identity", "Issues RS256 tokens, JWKS at /.well-known/jwks.json")
  SystemDb_Ext(neon, "Neon Postgres", "Project platform-commerce")
  System_Ext(sentry, "Sentry", "Project platform-commerce, errors only")
  System_Ext(uptime, "platform-uptime-worker", "Hourly GET /readyz")
  System_Ext(railway, "Railway", "Hosts the container, asia-southeast1, sleep on")
  System_Ext(payment, "platform-payment", "Staged; not called (D8)")
  Rel(owner, hub, "MCP call_cell")
  Rel(hub, identity, "client_credentials token, audience commerce-api")
  Rel(hub, gw, "HTTPS REST with bearer JWT")
  Rel(gw, commerce, "Proxy to Railway URL, token passed through")
  Rel(commerce, identity, "Fetch JWKS (HTTPS)")
  Rel(commerce, neon, "SQL over TLS, RLS per workspace")
  Rel(commerce, sentry, "Error events, no free text")
  Rel(uptime, commerce, "GET /readyz")
  Rel(railway, commerce, "Runs image, healthcheck /readyz")
```

หมายเหตุ: `platform-payment` แสดงไว้เพราะอยู่ใน `depends_on` ของ `contract.json` แต่ไม่มี call จริง (D8). `observability` ใน
`depends_on` คือ library/decision เปิดอยู่ (ops record) — ใน code มีแค่ Sentry และ `/metrics`.

Sources: ops record: api-gateway-edge (2026-11-03); `bookchaowalit-backend/platform-api-gateway@51c4711` `routes.json`; `bookchaowalit/platform-mcp-remote-worker@7d127c2` `wrangler.toml` `CELLS` + `src/worker.ts` `PLATFORM_CELLS`, `contract.json`, `src/platform_commerce/__main__.py`, `src/platform_commerce/_sentry.py`, `railway.toml`, `docs/runtime.md`, `PRODUCT.md`, ops record: book-platforms-status (2026-11-03)

## Open questions
- (ตอบแล้ว 2026-11-04) gateway มี route `platform-commerce` และ MCP hub เรียกผ่าน gateway; แต่ direct Railway URL ยังเปิดสาธารณะเพราะ service ไม่ตรวจ header ของ edge — จะปิด direct URL เมื่อไร (ต้องมี gateway-signed assertion ตาม ops record)?
- `/metrics` ไม่มี scraper (ops record: observability decision open) — ใครอ่าน?
