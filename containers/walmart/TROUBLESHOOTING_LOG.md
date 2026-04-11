# Walmart Scraper Troubleshooting Log

**Date:** 2026-04-10
**Goal:** Get Walmart scraper past PerimeterX anti-bot detection.
**Environment:** x86 EC2 t3.xlarge (`3.81.229.196`), us-east-1, Ubuntu 24.04
**Baseline failure:** `Bot detection triggered: Robot or human?` from existing `containers/walmart/extract.sh`

---

## Summary

**Result:** All 7 attempts FAILED. Walmart is unreachable from this EC2 IP regardless of fingerprint, headers, UA, viewport, or navigation pattern. **Root cause: AWS EC2 datacenter IP is blocklisted by PerimeterX at the IP/ASN layer.** Every request (Chromium, curl, different endpoints, mobile) returns the same `/blocked` redirect page.

**Recommendation:** Residential/mobile proxy required. Defer Walmart scraping until a proxy solution is added (Phase 3+). Alternative: Walmart Affiliate API or Walmart Open API.

---

## Attempts

### Attempt 1: Longer initial wait + slow human-like scroll

**Hypothesis:** PerimeterX may delay judgment a few seconds; slow human-paced scrolling may look more organic than rapid scrolls.

**Changes from baseline:**
- Initial `sleep 4` → `sleep 8` after Chromium launch
- Added 6-second wait after `networkidle`
- Replaced fast scroll (250-650px per step) with slow scroll (80-200px, 1.5-3.5s pauses)
- 8 scroll steps instead of 5

**Result:** `Title: "Robot or human?"` at **all 3 checkpoints** (post-launch, post-networkidle, post-scroll). Body confirmed PerimeterX challenge: `"Activate and hold the button to confirm that you're human"`.

**Diagnosis:** PerimeterX decided within the first 8 seconds. Slow scroll never got a chance — the block was already in place before any user interaction.

**Status:** FAILED

---

### Attempt 2: Real User-Agent + Accept-Language + full window size

**Hypothesis:** Maybe the default Chromium UA (`HeadlessChrome/...` or similar) is flagged. Spoofing a real macOS Chrome UA plus Accept-Language and a proper viewport may pass.

**Changes:**
- `--user-agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"`
- `--window-size=1920,1080`
- `--lang=en-US`
- `--accept-lang="en-US,en;q=0.9"`

**Result:** Title `"Robot or human?"` within 6 seconds. JS probe confirmed `navigator.userAgent` was correctly spoofed to the Chrome 131 Mac string but the block still triggered.

**Diagnosis:** PerimeterX fingerprints beyond the User-Agent string. Likely checks include:
- TLS fingerprint (JA3/JA4 hash) — Chromium's TLS stack differs from real Chrome
- Canvas/WebGL fingerprint
- Client hints (`navigator.userAgentData`) vs UA header mismatch
- IP reputation (datacenter IP)

**Status:** FAILED

---

### Attempt 3: Homepage warm-up first

**Hypothesis:** The existing code warns "NEVER use warm-up for Walmart" but that was from Phase 1. Maybe the situation changed. Establishing session cookies on the homepage first may help.

**Changes:**
- Launch Chromium on `https://www.walmart.com/` (NOT the search URL directly)
- Scroll homepage for 6 seconds
- THEN use `agent-browser open` to navigate to `/search?q=...`

**Result:**
- **Homepage loaded successfully!** Title: `"Walmart | Save Money. Live better."` — this is the first successful load of any Walmart page.
- After calling `ab open "/search?q=Sony+WH-1000XM5"`, the browser was immediately redirected to `https://www.walmart.com/blocked?url=...&uuid=...&vid=...&g=b`.
- The `vid` query param indicates PerimeterX assigned a tracked visit ID when the homepage loaded.

**Diagnosis:** Homepage is **whitelisted** (marketing funnel). `/search` is specifically blocked for this IP/fingerprint combination. PerimeterX distinguishes routes: `/` is public, `/search` and `/browse` require passing a stricter check.

**Status:** FAILED (partial progress — homepage loads)

---

### Attempt 4: Category page (browse like a human)

**Hypothesis:** Category pages like `/browse/electronics/headphones/...` may have different anti-bot rules than `/search`.

**Changes:**
- Direct navigation to `https://www.walmart.com/browse/electronics/headphones/3944_1096607_1102788`
- Rest of the flow identical

**Result:** Title `"Robot or human?"`. Redirected to `https://www.walmart.com/blocked?url=L2Jyb3dzZS9lbGVjdHJvbmljcy9oZWFkcGhvbmVzLzM5NDRfMTA5NjYwN18xMTAyNzg4&uuid=...`. Same block page as Attempts 1, 2, 5, 6, 7.

**Diagnosis:** Category `/browse/` routes are protected identically to `/search`. Only `/` (homepage) escapes the block for this IP.

**Status:** FAILED

---

### Attempt 5: Walmart mobile site (iPhone UA)

**Hypothesis:** Mobile traffic may use a separate rate-limiting tier. Walmart's anti-bot config may be more permissive for mobile browsers.

**Changes:**
- UA: `"Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"`
- Viewport: `--window-size=390,844` (iPhone 14 dimensions)
- Same `/search?q=...` URL

**Result:** Title `"Robot or human?"`, redirected to `/blocked?url=...`. JS probe confirmed `navigator.userAgent` reflected the iPhone UA but the block still triggered.

**Diagnosis:** Mobile UA + mobile viewport doesn't bypass the IP-level block. PerimeterX applies the same rules to mobile and desktop for this IP.

**Status:** FAILED

---

### Attempt 6: Homepage → form submit via JS (simulated user interaction)

**Hypothesis:** Since the homepage loads but direct `/search` navigation is blocked, maybe using the actual search box with a proper form submission event chain will preserve the human-like signature.

**Changes:**
- Launch on `https://www.walmart.com/` (homepage — known to work)
- Scroll briefly, then use JS to locate the search input (`input[type="search"], input[name="q"], input[aria-label*="Search"]`)
- Set input value via React-compatible setter (`Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set`)
- Dispatch `input` and `change` events
- Find closest `<form>` and call `form.submit()`
- Fall back to keyboard `Enter` event dispatch

**Result:**
- Homepage loaded: `"Walmart | Save Money. Live better."`
- Form was located: `input_name: "q"` (confirmed correct form)
- Form submission succeeded but triggered a navigation
- Post-submit title: `"Robot or human?"`, redirect to `/blocked?url=...&vid=7c5b92c5-...`
- The `vid` changed between homepage visit and blocked visit, showing PerimeterX did track the session but the block decision was remade at `/search`

**Diagnosis:** Even a real form submit originating from a legitimate homepage session gets blocked. The `/search` endpoint has a separate anti-bot gate that re-checks the client. Session continuity doesn't help — the block decision is per-request based on (IP + TLS fingerprint + headers), not session state.

**Status:** FAILED

---

### Attempt 7: Raw HTTP via curl (bypass Chromium entirely)

**Hypothesis:** If the block is TLS-fingerprint or Chromium-specific, a completely different HTTP client with Chrome-like headers might slip through.

**Changes:**
- No Chromium. Use `curl --compressed -L` with full Chrome header set:
  - `User-Agent: Chrome 131 macOS`
  - `Sec-Ch-Ua: "Google Chrome";v="131", "Chromium";v="131"`
  - `Sec-Ch-Ua-Platform: "macOS"`
  - `Sec-Fetch-Dest: document`, `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Site: none`
  - `Accept-Language: en-US,en;q=0.9`
  - `Accept-Encoding: gzip, deflate, br`

**Result:**
- First request: HTTP 307 redirect
- Followed to: `https://www.walmart.com/blocked?url=L3NlYXJjaD9xPVNvbnkrV0gtMTAwMFhNNQ==&uuid=abc449a2-...&vid=&g=b`
- Final HTTP 200 with **3369 bytes** of the block page
- Content: `<title>Robot or human?</title>` + PerimeterX challenge
- Zero `Sony`, `WH-1000XM5`, `data-item-id`, or `product-title` markers in response

**Diagnosis:** This is the **decisive finding**. curl has a completely different TLS fingerprint than Chromium, a totally different header order, no JavaScript, no canvas — and it gets the **exact same block** as every other attempt. The only shared property is the source IP (`3.81.229.196`).

**Conclusion: The block is at the IP/ASN level, not client fingerprinting.** PerimeterX has the AWS EC2 IP range flagged.

**Status:** FAILED

---

## Root Cause Analysis

PerimeterX is blocking at the IP reputation / ASN level:

1. **AWS EC2 IPs are datacenter IPs** — PerimeterX maintains a block list of known datacenter ASNs (AWS, GCP, Azure, DigitalOcean, Hetzner, etc.)
2. **Every request from `3.81.229.196` is blocked** regardless of:
   - Browser (Chromium vs curl)
   - TLS fingerprint (Chromium TLS stack vs curl's OpenSSL)
   - User-Agent (desktop Chrome, iPhone Safari)
   - Headers (full Chrome client hints)
   - Viewport (1920x1080 desktop vs 390x844 mobile)
   - Navigation pattern (direct, warm-up, form submit)
   - URL path (`/search`, `/browse`, category pages)
3. **Only the homepage (`/`)** bypasses this for marketing/SEO reasons — PerimeterX allows the landing page to prevent complete lockout of legit datacenter-based tools (search engines, previews, etc.)

---

## Recommendations

### Immediate (Phase 2-3)
1. **Mark Walmart as `blocked` in `retailer_health`** — the Watchdog should detect this state and avoid dispatching extractions until a proxy solution is available.
2. **Document in `docs/SCRAPING_AGENT_ARCHITECTURE.md`** — add a "Known Blocked Retailers" section listing Walmart with root cause.
3. **Do NOT waste Opus self-healing tokens on Walmart** — this isn't selector drift; no amount of JS rewriting will fix an IP block. Add retailer_id = "walmart" to the Watchdog's heal-skiplist.

### Phase 3+: Residential Proxy
1. **Residential proxy service** (Bright Data, Smartproxy, IPRoyal) — ~$75-300/mo for rotating residential IPs. Proven to bypass PerimeterX.
2. **Mobile 4G proxy** — Higher cost ($200-500/mo) but highest success rate. 4G IPs are virtually never blocked because they're shared across many real users.
3. **Residential via browser extension farm** — e.g., Bright Data SDK for user-consented proxying. Lower cost but requires legal/ethical review.

### Phase 4+: API Alternatives
1. **Walmart Affiliate Program** — free, legit, returns pricing data. Requires approval (usually granted for content/comparison sites).
2. **Walmart Open API** (`developer.walmart.com`) — free product search + affiliate API. Best long-term solution.
3. **Keepa** — aggregates Walmart data as part of its $15/mo plan.

### Not Recommended
- **Proxy + Chromium together** — the container architecture needs reshaping; inject proxy via `--proxy-server` flag and add retry logic on proxy failure. Defer to Phase 3 when the budget exists.
- **CAPTCHA solving services** (2captcha, anticaptcha) — $2-3/1000 solves, adds 15-30s per extraction, unreliable for "press and hold" challenges.
- **Scraping Walmart data from Google search** — may violate Google ToS.

---

## Files Modified

None. All 7 attempts used external probe scripts (`/tmp/walmart_attempt_*.sh`) that were copied into the container for testing. The production `containers/walmart/extract.sh` is unchanged — updating it is pointless until a proxy is available.

## Next Steps

1. Add Walmart to a `BLOCKED_RETAILERS` list in backend config
2. Update `docs/SCRAPING_AGENT_ARCHITECTURE.md` with this finding
3. Create a Phase 3 task for residential proxy integration
4. (Optional) Apply for Walmart Affiliate API as the permanent solution
