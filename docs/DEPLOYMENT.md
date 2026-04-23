# Barkain — Deployment & Infrastructure Reference

> Source: Architecture sessions, March–April 2026
> Scope: Local dev environment, backend deployment, iOS distribution, CI/CD, environment variables
> Last updated: April 2026 (v2.1 — docker-compose spec updated with postgres-test + LocalStack; Step 2h background workers section + cron schedule + prod SQS setup)

---

## Local Development Environment

### docker-compose.yml

```yaml
services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: barkain-db
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: barkain
      POSTGRES_USER: app
      POSTGRES_PASSWORD: localdev
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d barkain"]
      interval: 5s
      timeout: 3s
      retries: 5

  postgres-test:
    image: timescale/timescaledb:latest-pg16
    container_name: barkain-db-test
    ports: ["5433:5432"]
    environment:
      POSTGRES_DB: barkain_test
      POSTGRES_USER: app
      POSTGRES_PASSWORD: test
    tmpfs: ["/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d barkain_test"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: barkain-redis
    ports: ["6379:6379"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # Step 2h — SQS emulation for background workers.
  localstack:
    image: localstack/localstack:3
    container_name: barkain-localstack
    ports: ["4566:4566"]
    environment:
      SERVICES: sqs
      DEFAULT_REGION: us-east-1
      EAGER_SERVICE_LOADING: "1"
      DEBUG: "0"
    volumes:
      - localstack-data:/var/lib/localstack
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:4566/_localstack/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 3

volumes:
  pgdata:
  localstack-data:
```

**Note:** LocalStack is only enabled for SQS (Step 2h). The retailer scraper containers (amazon/best_buy/walmart/target/…) are defined as commented stubs in the real `docker-compose.yml`; they run on EC2 in dev, not locally.

### Starting Local Dev

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Backend
cd backend
cp ../.env.example .env          # Fill in real values
pip install -r requirements.txt
alembic upgrade head             # Run migrations (path: infrastructure/migrations/)
uvicorn app.main:app --reload --port 8000

# 3. Tests
pytest --tb=short -q             # Backend tests (Docker PostgreSQL, NOT SQLite)
ruff check .                     # Lint

# 4. iOS
# Open Barkain.xcodeproj in Xcode
# Or use XcodeBuildMCP for build/test from Claude Code
```

---

## Environment Variables

### .env.example (Backend)

```bash
# ── Database ─────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://app:localdev@localhost:5432/barkain

# ── Cache ────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Auth ─────────────────────────────────────────────
CLERK_SECRET_KEY=sk_test_xxxxx
CLERK_PUBLISHABLE_KEY=pk_test_xxxxx

# ── Retail Data APIs (Phase 4 production optimization) ─
BEST_BUY_API_KEY=xxxxx
EBAY_CLIENT_ID=xxxxx
EBAY_CLIENT_SECRET=xxxxx
KEEPA_API_KEY=xxxxx

# ── UPC Resolution (Phase 1) ──────────────────────────
GEMINI_API_KEY=xxxxx
UPCITEMDB_API_KEY=xxxxx

# ── AI Models (Phase 1: UPC lookup, Phase 2: Watchdog, Phase 3: recommendations) ─
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx

# ── Watchdog (Phase 2) ──────────────────────────────────
WATCHDOG_SLACK_WEBHOOK=https://hooks.slack.com/services/xxxxx  # Optional, for escalation notifications

# ── Affiliate (Phase 2) — superseded by the detailed block below ───

# ── Environment ──────────────────────────────────────
ENVIRONMENT=development          # development | staging | production
LOG_LEVEL=DEBUG                  # DEBUG | INFO | WARNING | ERROR
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# ── Rate Limiting ────────────────────────────────────
RATE_LIMIT_GENERAL=60            # per minute (free tier base)
RATE_LIMIT_WRITE=30              # per minute (free tier base)
RATE_LIMIT_AI=10                 # per minute (free tier base)
RATE_LIMIT_PRO_MULTIPLIER=2      # pro tier = base × this (Step 2f)

# ── Billing / RevenueCat (Step 2f) ───────────────────
# Shared bearer token used to validate POST /api/v1/billing/webhook against
# the value configured in RevenueCat dashboard → Project Settings →
# Integrations → Webhooks → Authorization. Required for the webhook to
# accept events; misconfigured = 401 WEBHOOK_AUTH_FAILED.
REVENUECAT_WEBHOOK_SECRET=

# ── Affiliate Programs (Step 2g) ─────────────────────
# Amazon Associates store ID — live, appended as ?tag=<id> to Amazon URLs.
AMAZON_ASSOCIATE_TAG=barkain-20
# eBay Partner Network campaign ID — live, drives rover.ebay.com redirects.
EBAY_CAMPAIGN_ID=5339148665
# Walmart Impact Radius affiliate ID — placeholder, pending approval.
# Leave empty to pass Walmart URLs through untagged.
# WALMART_AFFILIATE_ID=
# Shared bearer token for POST /api/v1/affiliate/conversion placeholder.
# Leave empty to accept any request (permissive placeholder mode). Once set,
# enforces Authorization: Bearer <secret> and 401s on mismatch.
AFFILIATE_WEBHOOK_SECRET=

# ── Walmart Adapter Routing (post-Step-2a paradigm shift) ──
# Selects which path handles walmart scrapes. All other retailers always use
# the container dispatch. See docs/ARCHITECTURE.md#walmart-adapter-routing and
# docs/SCRAPING_AGENT_ARCHITECTURE.md Appendices A–C.
#   decodo_http  — DEFAULT. Production path via Decodo US residential proxy
#                  (flipped from `firecrawl` default on 2026-04-17 after
#                  Firecrawl's upstream started returning PerimeterX
#                  challenge pages 100% of the time on Walmart).
#   firecrawl    — legacy demo path via Firecrawl managed API, currently
#                  non-functional for Walmart. Retry logic now mirrors
#                  Decodo's (3 attempts on CHALLENGE, fail-fast on others).
#   container    — legacy browser container, broken on any cloud IP.
WALMART_ADAPTER=decodo_http

# ── Firecrawl (walmart demo path) ─────────────────────
# Get your API key from https://firecrawl.dev/app/api-keys
# Only required when WALMART_ADAPTER=firecrawl.
FIRECRAWL_API_KEY=fc-xxxxx

# ── Decodo residential proxy (walmart production path) ─
# Sign up at https://decodo.com → Residential Proxies → Authentication.
# Username is auto-prefixed with `user-` and suffixed with `-country-us` so
# you can put the bare dashboard username below. Only required when
# WALMART_ADAPTER=decodo_http.
DECODO_PROXY_USER=
DECODO_PROXY_PASS=
DECODO_PROXY_HOST=gate.decodo.com:7000
```

**Paradigm shift note.** As of April 2026 (post-Step-2a), walmart no longer runs through the browser-container path in any deployed environment. The 10 other retailers still use the container dispatch unchanged. This is the only retailer with adapter-based routing today, and the pattern is intentionally scoped to walmart via a single `if retailer_id == "walmart"` check in `container_client.py::_extract_one`. Broader migration to Firecrawl for all retailers is deferred — see `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix B.7 for the long-term recommendation.

**`.env.example` audit (Step 2b, PF-1, 2026-04-11).** The `.env.example` was audited as part of Step 2b to prevent a repeat of the SP-5 drift trap (wrong `CONTAINER_URL_PATTERN` format silently rotting in `.env` while `config.py` had the correct default). Changes:
- Duplicate defaults that merely echoed `backend/app/config.py` defaults were removed. Only genuine overrides that MUST differ from code defaults remain.
- `CONTAINER_URL_PATTERN` line removed entirely — it was the SP-5 root cause. The correct default (`http://localhost:{port}`) lives in `config.py` and should never be overridden in `.env` unless the deployment topology changes.
- `CONTAINER_TIMEOUT_SECONDS=180` added (matches the post-live-run baseline from SP-6).
- `DEMO_MODE=1` added as a comment — uncomment for local physical-device testing without Clerk auth. (Renamed from `BARKAIN_DEMO_MODE` in Step 2i-b; pydantic-settings now reads it directly into `settings.DEMO_MODE`.)
- **Rule:** if a value in `.env.example` matches the default in `config.py`, delete it from `.env.example`. The env file is for secrets and deployment-specific overrides only.

### iOS (Xcconfig)

```
# Config/Debug.xcconfig
API_BASE_URL = http:$()/$()/127.0.0.1:8000
CLERK_PUBLISHABLE_KEY = pk_test_xxxxx
REVENUECAT_API_KEY = test_xxxxx       # public RC API key, safe to commit

# Config/Release.xcconfig
API_BASE_URL = https:$()/$()/api.barkain.ai
CLERK_PUBLISHABLE_KEY = pk_live_xxxxx
REVENUECAT_API_KEY =                  # production RC API key, set at release

# Config/Secrets.xcconfig (gitignored)
# Real keys — not committed
```

**Rule:** Never hardcode secrets in Swift source. Reference via `Info.plist` build settings → `Bundle.main.infoDictionary`. The `$()/$()/` escaping prevents xcconfig from treating `//` as a comment.

**RevenueCat note (Step 2f).** `REVENUECAT_API_KEY` is the **public** RC API key — designed to ship in client bundles and safe to commit. The server-side `REVENUECAT_WEBHOOK_SECRET` lives in `backend/.env` and is the only secret half of the pair.

---

## Billing / RevenueCat Setup (Step 2f)

The Step 2f code (m11_billing module + iOS SubscriptionService + PaywallHost) is fully wired but depends on dashboard configuration that lives outside the repo. Mike completes these post-merge tasks before the paywall renders any products:

### RevenueCat dashboard

1. **Create the project** at https://app.revenuecat.com (one project per environment — staging vs production).
2. **Add the iOS app** under Project Settings → Apps → New App → iOS, with bundle id `com.molatunji3.barkain`.
3. **Configure App Store Connect integration**:
   - App Store Connect API key + issuer id under Project Settings → Apps → App Store Connect API Key.
   - This is what lets RC fetch transaction details from Apple.
4. **Create products** in App Store Connect first (Subscriptions group + non-consumable for lifetime), then sync them in RC under Products. Three products:
   - `lifetime` — non-consumable, e.g. $149.99
   - `yearly` — auto-renewable annual subscription, e.g. $59.99/yr
   - `monthly` — auto-renewable monthly subscription, e.g. $7.99/mo
5. **Create the entitlement** — Project Settings → Entitlements → New Entitlement → identifier exactly `Barkain Pro` (case-sensitive, has a space). Attach all 3 products.
6. **Create the offering** — Offerings → New Offering → identifier `default` → add the 3 products as packages (Annual / Monthly / Lifetime). The PaywallView reads from this offering by default.
7. **Configure the paywall layout** — Offerings → default → Paywall → choose a template, set copy + colors. The dashboard owns layout, not the iOS code.
8. **Configure the Customer Center** — Project Settings → Customer Center → set support URL, paths for cancel/refund/contact, theme. The `CustomerCenterView()` wrapper inherits these.
9. **Get the public API key** — Project Settings → API Keys → iOS → copy into `Config/Debug.xcconfig` (test key) and `Config/Release.xcconfig` (production key).
10. **Configure the webhook** — Project Settings → Integrations → Webhooks → New Webhook → URL `https://<barkain backend domain>/api/v1/billing/webhook`. Set the Authorization header to `Bearer <random secret you generate>`. Copy the same secret into `backend/.env` as `REVENUECAT_WEBHOOK_SECRET`. Mismatch → 401 / RC retries.

### Verification

- iOS build with the test API key: paywall sheet should render the offering's products. If you see a loading state forever, the offering isn't published or the API key is wrong.
- Backend webhook reachability test: hit `POST /api/v1/billing/webhook` with `curl` carrying the bearer token and a minimal `INITIAL_PURCHASE` event payload — should return `{"ok": true, "action": "processed", "type": "INITIAL_PURCHASE", "tier": "pro"}`.
- Status endpoint: `curl https://.../api/v1/billing/status` (with auth) should return the synced tier.

---

## Affiliate Setup (Step 2g)

Step 2g ships a fully wired affiliate URL router and click logger (backend `m12_affiliate` + iOS `InAppBrowserView`) but revenue depends on live affiliate program configuration. **Current status:**

| Network | Status | ID | Env var |
|---------|--------|----|---------| 
| Amazon Associates | ✅ **Live** | `barkain-20` | `AMAZON_ASSOCIATE_TAG` |
| eBay Partner Network | ✅ **Live** | Campaign `5339148665` | `EBAY_CAMPAIGN_ID` |
| Walmart (Impact Radius) | ⏳ **Pending approval** | — | `WALMART_AFFILIATE_ID` |
| Best Buy (CJ Affiliate) | ❌ **Denied** | — | passthrough |
| Home Depot / Lowe's / Target / others | ❌ **Not applied** | — | passthrough |

**Post-merge tasks (Mike):**

1. **Verify live clicks are being attributed.** Scan a product → tap an Amazon row → land in the in-app browser → open the debug tools on a real device via `https://associates.amazon.com` → confirm the `tag=barkain-20` parameter is honored by Amazon's attribution. Repeat for eBay via https://partnernetwork.ebay.com dashboard.
2. **Walmart Impact Radius approval.** Complete application at https://goto.walmart.com/. When approved, set `WALMART_AFFILIATE_ID=<id>` in `backend/.env` and restart uvicorn — no code change needed. The service flips from passthrough to tagged automatically.
3. **Conversion webhook (future).** Once affiliate networks are ready to send sale-attribution callbacks, set `AFFILIATE_WEBHOOK_SECRET=<random token>` in `backend/.env` and configure the same token as a bearer header in each network's dashboard (Amazon reports, eBay Partner Network reports, Impact Radius reports). The endpoint flips from permissive placeholder to enforced bearer auth automatically. Actual conversion payload processing is Phase 5.
4. **Best Buy retry.** Best Buy denied the initial CJ Affiliate application; revisit in Phase 3 with a higher-traffic case. Until then, Best Buy URLs pass through untagged.

**Testing locally.** With `.env` configured (`AMAZON_ASSOCIATE_TAG=barkain-20`, `EBAY_CAMPAIGN_ID=5339148665`):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/affiliate/click \
  -H "Content-Type: application/json" \
  -d '{"retailer_id": "amazon", "product_url": "https://www.amazon.com/dp/B0B2FCT81R"}'
# → {"affiliate_url": "https://www.amazon.com/dp/B0B2FCT81R?tag=barkain-20", "is_affiliated": true, "network": "amazon_associates", "retailer_id": "amazon"}

curl http://127.0.0.1:8000/api/v1/affiliate/stats
# → {"clicks_by_retailer": {"amazon": 1}, "total_clicks": 1}
```

Demo mode (`DEMO_MODE=1`) bypasses Clerk auth for these curl calls.

---

## Background Workers (Step 2h)

Step 2h ships four background worker commands plus a unified CLI runner at `scripts/run_worker.py`, backed by SQS. LocalStack emulates SQS locally via docker-compose; production points at real AWS SQS by leaving `SQS_ENDPOINT_URL` empty.

### Local setup

```bash
# 1. Start LocalStack (first time only — docker-compose has it now)
docker compose up -d localstack
docker compose ps  # confirm barkain-localstack is healthy

# 2. Create SQS queues (idempotent — safe to re-run)
python3 scripts/run_worker.py setup-queues
# Expected:
#   queue ready: barkain-price-ingestion -> http://localhost:4566/000000000000/...
#   queue ready: barkain-portal-scraping -> http://...
#   queue ready: barkain-discount-verification -> http://...

# 3. Inspect queues via aws CLI (optional)
aws --endpoint-url http://localhost:4566 sqs list-queues --region us-east-1
```

### Running each worker

```bash
# Enqueue stale products (one-shot, designed for cron)
python3 scripts/run_worker.py price-enqueue
# Expected: "price-enqueue done: N messages"
# Precondition: at least one product with prices.last_checked > 6h ago.
# Quick seed for testing:
#   docker exec barkain-db psql -U app -d barkain -c \
#     "UPDATE prices SET last_checked = NOW() - interval '7 hours' WHERE product_id IS NOT NULL LIMIT 1;"

# Process the ingestion queue (long-poll, Ctrl+C to stop)
python3 scripts/run_worker.py price-process

# Scrape portal rates (one-shot)
python3 scripts/run_worker.py portal-rates
# Expected: {"rakuten": N, "topcashback": N, "befrugal": N, "chase_shop_through_chase": 0, "capital_one_shopping": 0}

# Verify discount URLs (one-shot, weekly)
python3 scripts/run_worker.py discount-verify
# Expected: {"checked": N, "verified": N, "flagged": 0, "failed": 0, "deactivated": 0}
```

### Cron schedule (production, UTC)

```cron
# Price refresh enqueue — every 6 hours
0 */6 * * *   cd /path/to/barkain && python3 scripts/run_worker.py price-enqueue

# Portal rate scrape — offset 30m so it doesn't race the price enqueue
30 */6 * * *  cd /path/to/barkain && python3 scripts/run_worker.py portal-rates

# Discount program verification — weekly Sunday 04:00
0 4 * * 0     cd /path/to/barkain && python3 scripts/run_worker.py discount-verify

# Watchdog health check — nightly 03:00 (legacy, separate CLI)
0 3 * * *     cd /path/to/barkain && python3 scripts/run_watchdog.py --check-all
```

`price-process` is the one long-running command — run it as a systemd service or a supervised worker process, not from cron.

### Production AWS SQS setup

When ready to flip off LocalStack:

1. **Create real queues** via `aws sqs create-queue` or Terraform:
   ```bash
   aws sqs create-queue --queue-name barkain-price-ingestion --region us-east-1
   aws sqs create-queue --queue-name barkain-portal-scraping --region us-east-1
   aws sqs create-queue --queue-name barkain-discount-verification --region us-east-1
   ```

2. **IAM policy** for the worker host (EC2/ECS/Lambda role):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [{
       "Effect": "Allow",
       "Action": [
         "sqs:SendMessage",
         "sqs:ReceiveMessage",
         "sqs:DeleteMessage",
         "sqs:GetQueueUrl",
         "sqs:CreateQueue"
       ],
       "Resource": [
         "arn:aws:sqs:us-east-1:*:barkain-price-ingestion",
         "arn:aws:sqs:us-east-1:*:barkain-portal-scraping",
         "arn:aws:sqs:us-east-1:*:barkain-discount-verification"
       ]
     }]
   }
   ```

3. **Env vars in production**:
   ```
   SQS_ENDPOINT_URL=              # empty → boto3 uses default chain
   SQS_REGION=us-east-1
   # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY inherit from IAM role
   ```

4. **Optional: dead-letter queues.** Configure `maxReceiveCount` on each queue so messages that fail repeatedly land on a DLQ for manual inspection. Not wired in Step 2h (latent ops hardening item).

### Verification

```bash
# portal_bonuses populated
docker exec barkain-db psql -U app -d barkain -c \
    "SELECT portal_source, retailer_id, bonus_value, normal_value, is_elevated FROM portal_bonuses ORDER BY portal_source, retailer_id LIMIT 20;"

# discount_programs verification stamps
docker exec barkain-db psql -U app -d barkain -c \
    "SELECT program_name, last_verified, consecutive_failures, is_active FROM discount_programs ORDER BY last_verified DESC NULLS LAST LIMIT 10;"
```

---

## Backend Deployment

### MVP: Railway

| Setting | Value |
|---------|-------|
| Service | Python (auto-detected from requirements.txt) |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Region | US East |
| Plan | Pro ($5/mo + usage) |
| Custom domain | api.barkain.ai |

**Railway environment variables:** Same as `.env.example` but with production values. Set via Railway dashboard or CLI:

```bash
railway variables set DATABASE_URL="postgresql+asyncpg://..."
railway variables set REDIS_URL="redis://..."
# ... etc
```

**Database:** Railway PostgreSQL add-on (development) → AWS RDS (scale).
**Redis:** Railway Redis add-on (development) → AWS ElastiCache (scale).

### Scale: AWS (When Railway Limits Hit)

| Service | AWS Resource | Credits |
|---------|-------------|---------|
| Backend API | ECS Fargate (containerized FastAPI) | $10K YC credits |
| Database | RDS PostgreSQL 16 + TimescaleDB | $10K YC credits |
| Cache | ElastiCache Redis 7 | $10K YC credits |
| Queue | SQS (Phase 2 workers) | $10K YC credits |
| Storage | S3 (receipt images if needed) | $10K YC credits |
| Push | SNS → APNs (Phase 5) | $10K YC credits |
| Scraper containers | ECS Fargate (per-retailer) | $10K YC credits |

**Migration trigger:** When Railway latency exceeds 200ms p95, or monthly cost exceeds $100, or connection pooling becomes a bottleneck.

**Migration path:** Dockerize backend → push to ECR → deploy to ECS Fargate. Database: pg_dump from Railway PostgreSQL → restore to RDS. Redis: no migration needed (cache is ephemeral).

### SSE Streaming Endpoint (Step 2c)

`GET /api/v1/prices/{product_id}/stream` returns `text/event-stream` and can stay open for up to ~120s while Best Buy's container finishes. Uvicorn handles this natively — no config needed. But any reverse proxy in the path **must not buffer** the response body, or the iPhone receives every event at once at the end instead of as they arrive:

| Layer | Default buffering | Action required |
|---|---|---|
| **Uvicorn** | None — streams chunks as-generated. | ✅ None. |
| **nginx** | On by default (`proxy_buffering on`). | Set `proxy_buffering off;` for the `/api/v1/prices/*/stream` location, OR rely on the `X-Accel-Buffering: no` response header which nginx already honors (it's set by `modules/m2_prices/sse.py`). Also set `proxy_read_timeout 300s;` since SSE connections stay open. |
| **Cloudflare** | Buffers non-streaming responses; streaming is Enterprise-plan-only on the classic network. | Confirm plan before putting Cloudflare in front of the stream endpoint. Workers-based routing supports streaming on all plans. |
| **AWS ALB** | Buffers by default for HTTP/1.1. | Enable HTTP/2 or confirm response streaming behavior. ALB idle timeout must be ≥ max SSE duration (default 60s — bump to 300s). |
| **Railway** | Pass-through to upstream. | ✅ None. |

The `SSE_HEADERS` constant in `backend/modules/m2_prices/sse.py` already sets `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`, and `Connection: keep-alive`. That covers nginx out of the box. If a future layer sits between the user and Uvicorn, re-verify streaming end-to-end with `curl -N https://api.barkain.ai/api/v1/prices/<id>/stream` — events should arrive at their natural completion time, not all at once.

---

## iOS Build & Distribution

### Build Configurations

| Config | API Base URL | Logging | Analytics | Bundle ID Suffix |
|--------|-------------|---------|-----------|-----------------|
| Debug | `localhost:8000` / staging | Verbose (OSLog) | Disabled | `.debug` |
| Release | `api.barkain.ai` | Errors only | Enabled | (none) |

### Code Signing

**Development:** Automatic (Xcode managed)
**Distribution:** Manual (for CI reliability)

### TestFlight

- Internal testing: up to 100 testers, no review required
- External testing: up to 10,000, Beta App Review required
- Groups: `Alpha` (team), `Beta` (trusted users), `Public`

---

## Portal Scrape Lambda (Step 3g-A)

The portal_rates worker is wrapped in an AWS Lambda and triggered every 6
hours by EventBridge. **EC2 has no PG/Redis on the scraper host**, so the
Lambda is the production cron — it cannot share a host with the scraper
fleet.

### Why Lambda

* 30s/invocation × 120/month = ~7 GB-seconds — Lambda free tier covers
  400,000 GB-seconds.
* EC2 / Fargate cost $5+/month for 24/7 uptime to do one minute of work
  per six hours.
* Single artifact: container image, deployed via one shell script.

### Layout

```
infrastructure/lambda/portal_worker/
  handler.py          # Lambda entry — wraps run_portal_scrape + alerting
  requirements.txt    # Pinned deps (httpx, BS4, sqlalchemy, asyncpg, resend)
  Dockerfile          # public.ecr.aws/lambda/python:3.12
  deploy.sh           # ECR + Lambda + EventBridge wiring (idempotent)
  README.md           # Full prerequisites + IAM + Secrets Manager runbook
```

### Deploy (Mike)

```bash
export AWS_REGION=us-east-1
export LAMBDA_ROLE_ARN="arn:aws:iam::ACCT:role/barkain-portal-worker-role"
export SECRETS_ARN="arn:aws:secretsmanager:us-east-1:ACCT:secret:barkain/portal-worker-XXXX"

cd infrastructure/lambda/portal_worker && ./deploy.sh
```

Idempotent — re-run after every code change. First run also creates the
ECR repo, Lambda function, EventBridge rule, and invoke permission.

### Secrets Manager

One JSON-shaped secret named `barkain/portal-worker` containing
`DATABASE_URL`, the Resend creds, the feature flag, and the referral
URLs. Updating the JSON propagates on the next cold-start (or invoke
`update-function-configuration` to force a fresh container).

### Verify

```bash
aws lambda invoke --function-name barkain-portal-worker \
  --invocation-type Event --region us-east-1 /tmp/out.json
aws logs tail /aws/lambda/barkain-portal-worker --region us-east-1 --since 5m
```

Look for `portal scrape complete: {rakuten: N, topcashback: N, befrugal: N}`.
Zero rows for any portal increments `portal_configs.consecutive_failures`;
3 consecutive zeros triggers a Resend email (24h throttle on
`last_alerted_at`).

### Rollback

`aws events disable-rule --name barkain-portal-cron --region us-east-1` —
stops scheduled invocations without deleting anything. Last good
`portal_bonuses` rows continue to serve the iOS pill.

---

## CI/CD Pipeline

### GitHub Actions

#### `backend-tests.yml` — Every PR

```yaml
triggers: pull_request → main
steps:
  1. Checkout
  2. Set up Python 3.12
  3. Start PostgreSQL+TimescaleDB and Redis (service containers)
  4. Install dependencies (pip install -r requirements.txt -r requirements-test.txt)
  5. Run migrations (alembic upgrade head)
  6. Run tests (pytest --tb=short -q --cov=app)
  7. Lint (ruff check .)
  8. Upload coverage
```

#### `ios-tests.yml` — Every PR (when Barkain/ changes)

```yaml
triggers: pull_request → main (paths: Barkain/**, BarkainTests/**, BarkainUITests/**)
steps:
  1. Checkout
  2. Select Xcode version (xcode-select)
  3. Resolve SPM packages
  4. Run tests (xcodebuild test -scheme Barkain -destination 'platform=iOS Simulator,name=iPhone 16')
  5. SwiftLint
  6. Upload test results
```

#### `release.yml` — On tag push

```yaml
triggers: push tags v*
steps:
  1. Backend: Deploy to Railway (or build Docker image → push to ECR → deploy to ECS)
  2. iOS: Build archive → export IPA → upload to TestFlight
  3. Notify (Slack webhook or email)
```

### Required GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `RAILWAY_TOKEN` | Railway deployment |
| `DATABASE_URL` | Test database (CI service container) |
| `CLERK_SECRET_KEY` | Auth in CI tests |
| `APPLE_CERTIFICATE_P12` | iOS distribution certificate |
| `APPLE_CERTIFICATE_PASSWORD` | Certificate password |
| `APPLE_PROVISIONING_PROFILE` | Provisioning profile |
| `APP_STORE_CONNECT_API_KEY` | TestFlight upload |
| `APP_STORE_CONNECT_ISSUER_ID` | API auth |
| `APP_STORE_CONNECT_KEY_ID` | API auth |

---

## Database Operations

### Running Migrations

```bash
# Local
cd backend
alembic upgrade head

# Production (Railway)
railway run alembic upgrade head

# Production (AWS — via ECS exec)
aws ecs execute-command --cluster barkain --task $TASK_ID \
  --command "alembic upgrade head" --interactive
```

### Rollback

```bash
# Rollback one migration
alembic downgrade -1

# Rollback to specific revision
alembic downgrade abc123
```

**Rule:** Backward-compatible migrations only. Never drop columns or rename tables in production. Add new columns as nullable, backfill, then add constraints.

---

## Watchdog Cron

```bash
# Nightly health check + self-healing for all retailer containers
0 3 * * * cd /path/to/barkain && python scripts/run_watchdog.py --check-all
```

---

## Container Base Image

```bash
# Build the shared base image first (all retailer containers inherit from it)
docker build -t barkain-base:latest containers/base/

# Then build individual retailers:
docker build -t barkain-amazon containers/amazon/
docker build -t barkain-walmart containers/walmart/
# ... etc for each retailer
```

**Required extract.sh conventions** (see `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix D for full rationale):
- Every retailer's `extract.sh` must `exec 3>&1; exec 1>&2` at the top and emit the final JSON via `>&3`. Otherwise `agent-browser`'s progress output (`✓ Done`, `✓ Browser closed`) pollutes stdout and `server.py` returns `PARSE_ERROR`.
- `containers/base/entrypoint.sh` must `rm -f /tmp/.X99-lock /tmp/.X11-unix/X99` before starting Xvfb. Otherwise `docker restart` leaves a stale lock and every subsequent extraction dies with `Missing X server or $DISPLAY`.
- `EXTRACT_TIMEOUT` defaults to **180 s** (was 60 s in Phase 1). Best Buy's warmup + scroll + DOM eval routinely runs ~90 s on t3.xlarge, and Phase 1's 60 s limit killed every live extraction mid-run.
- Backend's `CONTAINER_TIMEOUT_SECONDS` must be **at least as large** as the container's `EXTRACT_TIMEOUT` or the backend disconnects before the container responds.

---

## Live dev loop — Mac backend + EC2 containers via SSH tunnel

> Rationale: agent-browser containers don't work on Apple Silicon (x86 emulation is 60–180 s per request per CLAUDE.md L13), but they run fine on a t3.large/xlarge EC2 instance. Rather than bake the backend into a container image and round-trip it to EC2 on every change, keep the backend on the Mac with hot reload / breakpoints / real env, and forward the container ports over SSH. No code change is required to swap between "local" and "remote" retailer runtimes.

```
┌────────────────┐                    ┌─────────────────────┐
│  Mac           │    SSH tunnel      │   EC2 t3.xlarge     │
│                │   (8081→8091)      │                     │
│  uvicorn       │ ◄──────────────────┤  barkain-amazon     │ ← port 8081
│  :8000         │                    │  barkain-bestbuy    │ ← port 8082
│  ↑             │                    │  barkain-walmart    │ ← port 8083
│  iPhone LAN IP │                    │  ...                │
│  (physical dev)│                    │                     │
└────────────────┘                    └─────────────────────┘
```

### Scripts (committed on `phase-2/scan-to-prices-deploy`, pending merge to main)

- **`scripts/ec2_deploy.sh`** — run ON the EC2 instance. Installs Docker + git on first run, clones the repo, builds `barkain-base` then 3 priority retailers (amazon/best_buy/walmart) or all 11 with `--all`, runs them on ports 8081–8091, health-checks each one. Idempotent on re-run.
- **`scripts/ec2_tunnel.sh <EC2_IP> [ssh_key_path]`** — run on the Mac. Kills any stale tunnel to that IP, opens `-L 8081:localhost:8081 … -L 8091:localhost:8091`, verifies each port responds on the Mac side. After this completes, the Mac backend's `CONTAINER_URL_PATTERN=http://localhost:{port}` reaches the EC2 containers unchanged.
- **`scripts/ec2_test_extractions.sh`** — run ON the EC2 instance. Fires a live Sony WH-1000XM5 + AirPods Pro request against every running container. Produces a pass/fail markdown table. Uses `max_listings` (not `max_results`).

### Typical iteration loop

```bash
# 0. One-time setup: launch or start the EC2 instance.
aws ec2 start-instances --instance-ids <id> --region us-east-1
aws ec2 wait instance-running --instance-ids <id> --region us-east-1
EC2_IP=$(aws ec2 describe-instances --instance-ids <id> --query 'Reservations[0].Instances[0].PublicIpAddress' --output text --region us-east-1)

# 1. SSH in and (re-)deploy containers. Incremental rebuilds from a warm base image are ~15s.
ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@$EC2_IP
  cd ~/barkain && git pull && bash scripts/ec2_deploy.sh
  bash scripts/ec2_test_extractions.sh   # live smoke test
  exit

# 2. Open the tunnel on the Mac.
bash scripts/ec2_tunnel.sh $EC2_IP ~/.ssh/barkain-scrapers.pem

# 3. Run backend locally. --host 0.0.0.0 is required for physical iPhone access.
cd backend && set -a && source ../.env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Iterate on backend code as normal — uvicorn hot-reloads. Container images only
#    need rebuilding when extract.sh / extract.js / server.py / entrypoint.sh changes.
#
#    For rapid iteration on a single extract.js/extract.sh (e.g. debugging a live
#    DOM drift), you can hot-patch a running container via `docker cp` instead of
#    a full rebuild:
#
#      scp -i ~/.ssh/barkain-scrapers.pem containers/amazon/extract.js ubuntu@$EC2_IP:/tmp/extract.js
#      ssh -i ~/.ssh/barkain-scrapers.pem ubuntu@$EC2_IP \
#        "docker cp /tmp/extract.js amazon:/app/extract.js"
#
#    WARNING: hot-patches only survive until the container is stopped. A
#    `docker stop <retailer>` or `aws ec2 stop-instances` reverts to the image's
#    original file. Before closing a session, run `scripts/ec2_deploy.sh` (or
#    equivalent) so the image on disk matches the repo. Otherwise the next
#    stop/start wipes the patch silently.

# 5. When done for the day:
kill $(pgrep -f "ssh.*$EC2_IP.*-N")                   # close tunnel
aws ec2 stop-instances --instance-ids <id> --region us-east-1
```

### Cost + caveats

- `t3.large` ~$0.08/hr, `t3.xlarge` ~$0.17/hr. Stop when idle; EBS persists at ~$2.40/mo so the pre-built `barkain-base` image survives across sessions.
- Public IP rotates on stop/start unless you assign an Elastic IP. Tunnel script takes `$EC2_IP` as a positional arg so re-running with the new IP is fine.
- Security group must allow port 22 from your current Mac IP. `curl -s -4 ifconfig.me` gets it; re-run `aws ec2 authorize-security-group-ingress` whenever you change networks.
- The backend needs `--host 0.0.0.0` (not `--host localhost`) for physical iPhone testing over WiFi.
- iOS `Config/Debug.xcconfig` must have `API_BASE_URL = http://<mac-lan-ip>:8000` for physical device builds. Info.plist's `NSAllowsLocalNetworking=true` permits the HTTP LAN connection.
- **Env sync:** after any Step 1 → Step 2 style config shape change, verify that `.env` overrides still match `backend/app/config.py` defaults. 2/7 live-run bugs on 2026-04-10 were `.env` overrides silently rotting. See `Barkain Prompts/Error_Report_Scan_to_Prices_Deployment.md` SP-5 / SP-6.

---

## Health Monitoring

### Backend Health Endpoint

```
GET /api/v1/health

Response:
{
  "status": "healthy",
  "database": "connected",
  "redis": "connected",
  "version": "0.1.0",
  "timestamp": "2026-04-03T12:00:00Z"
}
```

### Monitoring Stack

| Layer | Tool | Phase |
|-------|------|-------|
| Application logs | Structured JSON (stdout → Railway/CloudWatch) | 1 |
| Error tracking | Sentry (or Firebase Crashlytics) | 4 |
| Metrics | AWS CloudWatch | 2+ |
| Uptime | Railway health checks / AWS ALB health | 1 |

---

## App Store Submission Checklist (Phase 4)

### Before First Submission
- [ ] App Store Connect app record created
- [ ] Bundle ID registered
- [ ] Privacy policy at barkain.ai/privacy
- [ ] App Privacy nutrition labels (see AUTH_SECURITY.md)
- [ ] Export compliance declarations
- [ ] Age rating questionnaire
- [ ] FTC affiliate disclosure in app + App Store description
- [ ] Amazon Associates required disclosure text

### Per-Release Checklist
- [ ] Version number bumped
- [ ] Build number incremented
- [ ] All tests passing (backend + iOS)
- [ ] Physical device testing
- [ ] Screenshots for required device sizes
- [ ] Release notes
- [ ] Demo account credentials (if login required for review)

### Required Screenshots

| Device | Size | Required |
|--------|------|----------|
| iPhone 6.9" (16 Pro Max) | 1320 × 2868 | Yes |
| iPhone 6.3" (16 Pro) | 1206 × 2622 | Yes |
| iPhone 6.7" (16 Plus) | 1290 × 2796 | Optional |

---

## Versioning Strategy

- **Marketing version:** `MAJOR.MINOR.PATCH` (MAJOR = redesign, MINOR = feature, PATCH = fix)
- **Build number:** Auto-increment in CI, unique per App Store upload
- **Git tags:** `v0.N.0` at phase boundaries
