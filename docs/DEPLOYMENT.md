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

# ── AI Models (Phase 1: UPC lookup, Phase 3: recommendations) ─
ANTHROPIC_API_KEY=sk-ant-xxxxx
OPENAI_API_KEY=sk-xxxxx

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
```

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
