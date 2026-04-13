# Barkain — Deployment & Infrastructure Reference

> Source: Architecture sessions, March–April 2026
> Scope: Local dev environment, backend deployment, iOS distribution, CI/CD, environment variables
> Last updated: April 2026 (v2 — complete rewrite: docker-compose spec, backend deployment, env var inventory, Railway + AWS paths)

---

## Local Development Environment

### docker-compose.yml

```yaml
version: "3.9"

services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: barkain-db
    ports:
      - "5432:5432"
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

  redis:
    image: redis:7-alpine
    container_name: barkain-redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

**Note:** LocalStack (SQS/S3/SNS) is NOT included — added in Phase 2 when background workers are built.

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

# ── Affiliate (Phase 2) ─────────────────────────────
AMAZON_ASSOCIATE_TAG=barkain-20
EBAY_CAMPAIGN_ID=xxxxx
CJ_WEBSITE_ID=xxxxx

# ── Environment ──────────────────────────────────────
ENVIRONMENT=development          # development | staging | production
LOG_LEVEL=DEBUG                  # DEBUG | INFO | WARNING | ERROR
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# ── Rate Limiting ────────────────────────────────────
RATE_LIMIT_GENERAL=60            # per minute
RATE_LIMIT_WRITE=30              # per minute
RATE_LIMIT_AI=10                 # per minute

# ── Walmart Adapter Routing (post-Step-2a paradigm shift) ──
# Selects which path handles walmart scrapes. All other retailers always use
# the container dispatch. See docs/ARCHITECTURE.md#walmart-adapter-routing and
# docs/SCRAPING_AGENT_ARCHITECTURE.md Appendices A–C.
#   container    — legacy browser container (broken on any cloud, do not use)
#   firecrawl    — demo path via Firecrawl managed API (default for demo)
#   decodo_http  — production path via Decodo residential proxy
WALMART_ADAPTER=firecrawl

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
- `BARKAIN_DEMO_MODE=1` added as a comment — uncomment for local physical-device testing without Clerk auth.
- **Rule:** if a value in `.env.example` matches the default in `config.py`, delete it from `.env.example`. The env file is for secrets and deployment-specific overrides only.

### iOS (Xcconfig)

```
# Config/Debug.xcconfig
API_BASE_URL = http://localhost:8000
CLERK_PUBLISHABLE_KEY = pk_test_xxxxx

# Config/Release.xcconfig
API_BASE_URL = https://api.barkain.ai
CLERK_PUBLISHABLE_KEY = pk_live_xxxxx

# Config/Secrets.xcconfig (gitignored)
# Real keys — not committed
```

**Rule:** Never hardcode secrets in Swift source. Reference via `Info.plist` build settings → `Bundle.main.infoDictionary`.

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
