# Barkain — Auth & Security Reference

> Source: Architecture sessions, March–April 2026
> Scope: Authentication flow, authorization, rate limiting, security headers, compliance
> Last updated: April 2026 (v1.1 — tier-aware rate limiting + RevenueCat webhook auth documented after Steps 2f/2g; free-tier scan limit corrected to 10/day)

---

## Authentication: Clerk

### Flow

```
iOS App                          Backend                         Clerk
───────                          ───────                         ─────
1. User signs in via Clerk SDK
   (email, Google, Apple Sign-In)
                                                          ← JWT issued

2. APIClient includes JWT in
   Authorization: Bearer <token>
                          ──────►
3.                        Middleware extracts token
                          Validates via Clerk SDK
                          (clerk-backend-api library)
                          Extracts user_id from claims
                          Attaches to request context
                          ──────►
4.                        Endpoint accesses user_id
                          via dependency injection
```

### JWT Validation (Backend Dependency)

```python
# dependencies.py — Clerk JWT validation via authenticate_request()
from clerk_backend_api import Clerk
from clerk_backend_api.security import AuthenticateRequestOptions

clerk = Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY"))

async def get_current_user(request: Request, authorization: str | None = Header(None)) -> dict:
    """Validate Clerk JWT and return user context. Raises 401 if invalid."""
    # Extract Bearer token from Authorization header
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, ...)

    # clerk-backend-api v5.x uses authenticate_request(), NOT verify_token()
    # SDK handles: JWKS fetching, signature verification, expiry, issuer validation
    request_state = clerk.authenticate_request(
        request,
        AuthenticateRequestOptions(),
    )
    if not request_state.is_signed_in:
        raise HTTPException(401, ...)

    payload = request_state.payload or {}
    return {
        "user_id": payload.get("sub", ""),   # Clerk user_id (string)
        "email": payload.get("email"),
        "session_id": payload.get("sid"),
    }
```

### Endpoint Protection

| Endpoint | Auth Required | Notes |
|----------|--------------|-------|
| `GET /api/v1/health` | No | Public health check |
| All other endpoints | Yes | Clerk JWT required |

### Subscription Tier Checking

```python
async def require_pro(user_id: str, db: AsyncSession):
    """Raise 403 if user is not on Pro tier."""
    user = await db.get(User, user_id)
    if user.subscription_tier != "pro":
        raise HTTPException(403, detail={"error": {"code": "PRO_REQUIRED"}})
    if user.subscription_expires_at and user.subscription_expires_at < datetime.now(datetime.UTC):
        raise HTTPException(403, detail={"error": {"code": "SUBSCRIPTION_EXPIRED"}})
```

| Feature | Free Tier | Pro Tier (~$7.99/mo) |
|---------|-----------|---------------------|
| Price comparison (11 retailers) | ✅ | ✅ |
| Barcode scanning | ✅ (10/day, local TZ rollover) | ✅ (unlimited) |
| Identity discount display | ✅ (first 3 shown, rest locked) | ✅ (full list + stacking) |
| Card recommendation | ❌ (banner + upgrade CTA) | ✅ |
| Portal bonus stacking | ❌ | ✅ (Phase 3) |
| AI recommendation (Claude) | ❌ | ✅ (Phase 3) |
| Receipt scanning | ❌ | ✅ (Phase 3) |
| Price prediction | ❌ | ✅ (Phase 4) |
| Watched items | ❌ | ✅ (Phase 4) |

Free-tier gates are enforced by `FeatureGateService` on iOS (daily scan counter persisted to `UserDefaults` keyed on `yyyy-MM-dd` in the **local** timezone) and by the tier-aware rate limiter on the backend. Scan quota is gated **after** a successful product resolve, so failed barcode reads or unknown UPCs don't burn quota — a better UX than strict pre-check.

---

## Rate Limiting

Redis-backed, per-user, sliding window.

### Tiers

Free-tier baseline, per category:

| Endpoint Category | Free Limit | Pro Limit | Window | Key |
|---|---|---|---|---|
| General read endpoints | 60 requests | 120 requests | 1 minute | `rate:{user_id}:general` |
| Write endpoints (POST/PUT) | 30 requests | 60 requests | 1 minute | `rate:{user_id}:write` |
| AI-heavy endpoints (recommend, identify, receipt scan) | 10 requests | 20 requests | 1 minute | `rate:{user_id}:ai` |
| Health check | Exempt | Exempt | — | — |
| Unauthenticated | 10 requests | — | 1 minute | `rate:{ip}:unauth` |

Pro multiplier (default 2x) is configured via `settings.RATE_LIMIT_PRO_MULTIPLIER` and applied to all three authenticated categories. Subscription tier is resolved per-request by `_resolve_user_tier` in `backend/app/dependencies.py`:

1. Read `tier:{user_id}` from Redis (60s TTL)
2. On miss: SELECT `subscription_tier`, `subscription_expires_at` FROM `users` WHERE id = $1. Pro requires `tier == "pro" AND (expires_at IS NULL OR expires_at > now())` — expired-pro rows resolve to free. Missing user row → free (not an error).
3. Cache the resolved string (`"pro"` or `"free"`) into Redis with the 60s TTL so the SSE hot path doesn't pay a Postgres roundtrip per event.

`m11_billing.service.process_webhook` busts `tier:{user_id}` on every state-changing event so upgrades/downgrades take effect within the cache window. Falls open to free on Redis or DB errors — the rate limiter never hard-fails an authenticated request because of an infrastructure blip.

### Webhook Authentication (Step 2f)

`POST /api/v1/billing/webhook` does NOT use Clerk auth. It validates a fixed bearer token from RevenueCat's webhook configuration:

```
Authorization: Bearer ${REVENUECAT_WEBHOOK_SECRET}
```

The shared secret is configured in two places: the RevenueCat dashboard (Project Settings → Integrations → Webhooks → Authorization) and the backend `.env` file (`REVENUECAT_WEBHOOK_SECRET=...`). Mismatch → 401 with `code=WEBHOOK_AUTH_FAILED`. Empty secret in env → 401 (treated as misconfiguration). All other errors (parse failure, unknown event type) return 200 to prevent RevenueCat retry storms.

### Response on Rate Limit

```json
HTTP 429 Too Many Requests
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Try again in 42 seconds.",
    "details": {
      "retry_after_seconds": 42
    }
  }
}
```

Header: `Retry-After: 42`

---

## CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

ALLOWED_ORIGINS = {
    "development": ["http://localhost:3000", "http://localhost:8000"],
    "staging": ["https://staging.barkain.ai"],
    "production": [
        "https://app.barkain.ai",       # Web dashboard
        "https://api.barkain.ai",       # API (for Swagger UI)
    ],
}
# Note: iOS native app does NOT need CORS — it makes direct HTTP requests
# CORS is only for browser-based clients (web dashboard, Swagger UI)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS[ENVIRONMENT],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
```

---

## Security Headers

Applied to all responses via middleware:

```python
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Request-ID"] = request.state.request_id
    return response
```

---

## Data Security

### What Barkain Stores

| Data Category | What's Stored | What's NOT Stored |
|---|---|---|
| Identity profile | Boolean flags (is_military, is_student, etc.) | Government IDs, verification documents |
| Card portfolio | Card name, issuer, network (from catalog) | Card numbers, CVVs, expiration dates, billing addresses |
| Receipts | Store name, item names, prices, totals | Full receipt images (OCR'd on-device, only text sent) |
| Auth | Clerk user_id (string reference) | Passwords (Clerk handles auth entirely) |
| Shopping behavior | Products searched, prices compared, affiliate clicks | Browsing history outside the app |

### Encryption

| Layer | Method |
|---|---|
| In transit | TLS 1.3 (enforced by Railway/AWS) |
| At rest (database) | AWS RDS encryption (AES-256) |
| At rest (cache) | AWS ElastiCache encryption at rest |
| At rest (S3) | S3 default encryption (SSE-S3) |

### No Card Numbers — Ever

Barkain stores card *products* (e.g., "Chase Sapphire Preferred"), not card *numbers*. Users select from a catalog of card products. There is no PCI DSS scope because no payment card data is collected, processed, or stored.

---

## FTC Compliance (Affiliate Disclosure)

### Requirements

The Federal Trade Commission requires clear disclosure when earning commissions on recommended purchases.

### In-App Disclosure

| Location | Disclosure |
|---|---|
| Settings / About screen | "Barkain earns commissions when you purchase through our links. This doesn't affect the prices you pay." |
| Before affiliate redirect | Brief note in CardInterstitialView or PriceRow tap action |
| App Store description | "Barkain may earn affiliate commissions on purchases made through the app." |

### Amazon-Specific

Amazon Associates requires this exact phrase somewhere publicly visible: "As an Amazon Associate, Barkain earns from qualifying purchases."

---

## Privacy Compliance

### CCPA (California Consumer Privacy Act)

| Requirement | Implementation |
|---|---|
| Right to know | Privacy policy describes all data collected |
| Right to delete | Account deletion via Clerk → cascading delete of all user data |
| Right to opt out of sale | Barkain does not sell personal data (Phase 1-4). If data monetization added (Phase 6+), opt-out mechanism required before launch |
| Privacy policy | Hosted at barkain.ai/privacy, linked from App Store and in-app settings |

### Apple App Store Privacy

| App Privacy Label | Category | Linked to Identity? |
|---|---|---|
| Identifiers | Clerk user_id | Yes |
| Purchases | Receipt data (items, prices) | Yes |
| Usage Data | Products searched, prices compared | Yes |
| Diagnostics | Crash logs, performance data | No |

Data NOT collected: location, contacts, browsing history, financial information (card numbers), health data.

### GDPR (if/when expanding internationally)

Not in scope for US-only MVP. Architecture is designed to support data export and deletion requests if needed later.

---

## Incident Response

### If an API Key Is Leaked

1. Rotate the key immediately in the provider's dashboard
2. Update Railway/AWS environment variables
3. Verify no unauthorized usage in provider's logs
4. If Clerk key: additionally revoke all active sessions

### If User Data Is Compromised

1. Assess scope (what data, how many users)
2. Notify affected users within 72 hours (CCPA requirement if California residents)
3. File breach notification if >500 California residents affected
4. Document incident, remediation, and prevention measures

---

## Security Audit Checklist (Run at Phase Boundaries)

- [ ] All secrets in environment variables, none in code or git history
- [ ] `.env` is in `.gitignore`
- [ ] Clerk JWT validation is active on all protected endpoints
- [ ] Rate limiting is active and tested
- [ ] CORS origins are restricted to known domains
- [ ] Security headers present on all responses
- [ ] No PII in application logs (redact user_id in structured logs if needed)
- [ ] Database user is app role, not superuser
- [ ] S3 bucket is not publicly accessible
- [ ] Dependencies scanned for known vulnerabilities (`pip audit`, `npm audit`)
