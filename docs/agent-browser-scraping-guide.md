# Building E-Commerce Scraping Scripts with agent-browser

A field guide documenting how `agent-browser` CLI is being used to build extraction scripts across major retail sites. Based on hands-on testing of 5 sites (Walmart, Amazon, Target, Facebook Marketplace, Costco) with 6-7 extraction methods each, totaling 35+ individual method tests and 100+ live requests.

---

## Table of Contents

1. [What is agent-browser](#what-is-agent-browser)
2. [The Methodology: 6-Method Battery Test](#the-methodology)
3. [Core Architecture of Every Script](#core-architecture)
4. [Method Comparison Across All Sites](#method-comparison-across-all-sites)
5. [The Winning Pattern: DOM Eval](#the-winning-pattern-dom-eval)
6. [Site-Specific Findings](#site-specific-findings)
7. [Anti-Detection Strategies](#anti-detection-strategies)
8. [Bot Detection Thresholds](#bot-detection-thresholds)
9. [The Anchor Selector Pattern](#the-anchor-selector-pattern)
10. [Shell Scripting Patterns](#shell-scripting-patterns)
11. [Common Pitfalls and Fixes](#common-pitfalls-and-fixes)
12. [Proxy and Scaling](#proxy-and-scaling)
13. [Production Script Template](#production-script-template)

---

## What is agent-browser

`agent-browser` is a CLI tool that controls Chrome/Chromium via the Chrome DevTools Protocol (CDP). It provides commands for navigation, DOM interaction, screenshots, JavaScript evaluation, and network inspection — all from the terminal.

```bash
npm i -g agent-browser    # install
agent-browser install      # download Chrome
```

Key commands used in scraping:

| Command | Purpose |
|---------|---------|
| `open <url>` | Navigate to a page |
| `snapshot -i` | Capture accessibility tree with interactive element refs |
| `snapshot -s "<selector>"` | Scope snapshot to a CSS selector |
| `get text body` | Extract all visible text |
| `screenshot [--full]` | Capture viewport or full page |
| `eval --stdin` | Run JavaScript in page context |
| `scroll down <px>` | Scroll to trigger lazy loading |
| `wait --load networkidle` | Wait for network activity to settle |
| `network requests` | Inspect captured XHR/fetch calls |
| `click @ref` | Click an element by snapshot ref |

The key differentiator vs. Puppeteer/Playwright: agent-browser is designed for **interactive CLI use and shell scripting**, not programmatic Node.js. This makes it ideal for rapid prototyping and bash-based automation pipelines.

---

## The Methodology

Every site is tested with the same 6-method battery, measuring time (ms), output size (bytes), listing count, field coverage, and data quality grade (A-F):

### Method 1: Full Snapshot (`snapshot -i`)
Captures the accessibility tree with interactive element refs (`@e1`, `@e2`, etc.). Returns a text representation of every semantic element on the page.

### Method 2: Plain Text (`get text body`)
Dumps all visible text content from the page body. Fastest method but completely unstructured.

### Method 3: Screenshot (`screenshot --full`)
Full-page PNG capture. Requires OCR or vision model to extract data. Largest output, slowest method.

### Method 4: DOM Eval (`eval --stdin`)
Runs targeted JavaScript to query specific DOM elements, extract text/attributes/URLs, and return structured JSON. **Consistently the winner across all sites.**

### Method 5: Scoped Snapshot (`snapshot -s "<selector>"`)
Accessibility tree scoped to a specific container. Eliminates nav/footer noise but still unstructured.

### Method 6: Inline Data / Network Intercept
Checks for `__NEXT_DATA__`, `application/ld+json`, GraphQL relay stores, embedded `<script>` data, and XHR/fetch API responses. Highly site-dependent.

---

## Core Architecture

Every production script follows the same 9-step pattern:

```
1. Kill stale Chrome / agent-browser sessions
2. Launch headed Chrome with anti-detection flags
3. Warm up on site homepage (jitter)
4. Navigate to search/listing page (jitter)
5. Bot detection check (title inspection)
6. Handle overlays/modals (if any)
7. Scroll to load lazy content (jitter between scrolls)
8. Extract via DOM eval (the actual scraping)
9. Validate output, pretty-print JSON, report stats
```

Wrapped in a retry loop (typically 2-3 attempts) with cleanup on exit via `trap`.

### Chrome Launch Flags

Every script launches Chrome the same way:

```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" \
  --remote-debugging-port=9222 \
  --user-data-dir="/tmp/chrome-scrape-$$" \
  --no-first-run --no-default-browser-check \
  --disable-blink-features=AutomationControlled \
  "about:blank" &
```

Critical flags:
- `--remote-debugging-port=9222`: Enables CDP for agent-browser to connect
- `--user-data-dir`: Fresh profile each run (no cookie accumulation)
- `--disable-blink-features=AutomationControlled`: Prevents `navigator.webdriver=true` detection
- `"about:blank"`: Start blank, navigate via agent-browser (except Walmart — see below)

---

## Method Comparison Across All Sites

### Speed (ms) — lower is better

| Method | Walmart | Amazon | Target | Facebook | Costco | Avg |
|--------|---------|--------|--------|----------|--------|-----|
| 1. Snapshot | 688 | 1,170 | 752 | 535 | 1,262 | **881** |
| 2. Text | 531 | 560 | 473 | 687 | 660 | **582** |
| 3. Screenshot | - | 3,720 | 4,807 | 961 | 3,451 | **3,235** |
| **4. DOM Eval** | **510** | **480** | **452** | **528** | **603** | **515** |
| 5. Scoped | 832 | - | 716 | 654 | 1,025 | **807** |
| 6. Inline data | 678 | - | - | 494 | 632 | **601** |

### Data Quality Grade

| Method | Walmart | Amazon | Target | Facebook | Costco |
|--------|---------|--------|--------|----------|--------|
| 1. Snapshot | B+ | A- | B+ | **F** | B+ |
| 2. Text | D | B | B | B- | B |
| 3. Screenshot | - | D | D | D | C+ |
| **4. DOM Eval** | **A-** | **A** | **A** | **A** | **A** |
| 5. Scoped | B | - | B | **F** | A- |
| 6. Inline data | F | - | - | C- | F |

### Key Takeaways

1. **DOM eval wins every time** — fastest AND highest quality across all 5 sites
2. **Snapshots fail on Facebook** — a11y tree is gated behind auth
3. **Screenshot is always the worst** — slowest, largest, requires separate OCR
4. **Inline data is unreliable** — only Facebook had partial data; Walmart, Costco, Target had none
5. **Plain text is the best fallback** — fast, compact, parseable with regex

---

## The Winning Pattern: DOM Eval

Every production extraction uses the same JavaScript structure:

```javascript
(() => {
  // 1. Select all product cards via a stable selector
  const cards = document.querySelectorAll('ANCHOR_SELECTOR');
  
  // 2. Deduplicate (some sites render duplicates)
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const key = el.href || el.getAttribute('data-id');
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const text = el.innerText.trim();
    // Parse price, title, location from text or child elements
    return {
      position: i + 1,
      id: /* from URL or data attribute */,
      title: /* from heading or text */,
      price: /* from price element or regex */,
      image: /* from img.src */,
      url: /* from href */
    };
  });

  // 4. Return as JSON with metadata
  return JSON.stringify({
    metadata: { url: location.href, extracted_at: new Date().toISOString(), count: listings.length },
    listings
  }, null, 2);
})()
```

This runs in the page context via:
```bash
agent-browser --cdp 9222 eval --stdin < extract.js > output.json
```

---

## Site-Specific Findings

### Walmart
- **Bot detection:** PerimeterX — **never use `agent-browser open`** for navigation; it triggers captcha 100% of the time. Must launch Chrome directly with the target URL.
- **Anchor selector:** `[data-item-id]` — data attribute on every product card
- **Price gotcha:** Prices rendered as `<span>$</span><span>269</span><span>98</span>` — three separate elements. Use `innerText` of the price container, not individual spans.
- **`__NEXT_DATA__`:** 1.3MB blob with zero product data — pure config/A-B-test data.
- **Inline data verdict:** Useless. Products loaded via client-side XHR after hydration.

### Amazon
- **Bot detection:** Moderate. Headed Chrome with anti-detection flags works. Headless gets blocked.
- **Anchor selector:** `[data-component-type="s-search-result"]` + `data-asin` attribute
- **Title gotcha:** Two layouts — phones use `h2 > a > span`, accessories use brand in `h2` + product name in sibling span. Need fallback chain: `[data-cy="title-recipe"]` spans > `h2 a span` > `img.alt`.
- **Sponsored noise:** Title text includes "Sponsored", "You're seeing this ad", "Leave ad feedback" — must be cleaned aggressively.
- **Price gotcha:** `.a-price-whole` + `.a-price-fraction` are separate elements.
- **Review count:** Rendered inside `<a>` tags with dynamic handlers — `getAttribute('href')` returns null.
- **Richest extraction:** 17 fields achievable (title, price, list price, rating, reviews, bought/month, condition, sponsored, stock, delivery, display size, memory, other offers, image, ASIN).

### Target
- **Bot detection:** Occasional. Headed Chrome reliable.
- **Anchor selector:** `[data-test="@web/site-top-of-funnel/ProductCardWrapper"]` — clean `data-test` attributes on everything.
- **Wait strategy:** Use `wait --load load` (not `networkidle`) — Target's analytics pixels fire indefinitely. Then `wait "[data-test='product-grid']"` for the actual content.
- **Richest fields:** brand, price, MSRP, sale flag, rating, reviews, bought last month, badges ("Highly rated"), loved for, stock status, fulfillment, sponsored, swatches, Target item ID.

### Facebook Marketplace
- **Login wall:** Modal overlay blocks page. **Hide it (`display: none`), don't remove it (`.remove()` breaks React tree).**
- **Accessibility tree:** Completely gated behind auth — `snapshot` returns only login form elements. This is unique to Facebook among all tested sites.
- **Anchor selector:** `a[href*="/marketplace/item/"]` — URL pattern is the only stable selector (class names are obfuscated and change regularly).
- **GraphQL data:** 53KB of Relay data in inline `<script>` tags, but prices are misaligned (current + original prices in flat sequence).
- **No login needed for data:** The DOM is fully rendered behind the CSS overlay. JavaScript eval accesses everything even without authentication.

### Costco
- **Bot detection:** None observed in 100 rapid-fire requests (see threshold testing below).
- **Anchor selector:** `a[href*=".product."]` — URL pattern. Also has excellent `data-testid` attributes (`ProductTile_<id>`, `PriceGroup_<id>`, `MemberOnlyItemBadge_<id>`).
- **Container:** `#productList` — clean, id-based.
- **Member pricing:** **Completely server-side gated.** Zero `$` signs in 19KB of raw HTML for member-only cards. No hidden elements, no data attributes, no inline scripts. Must authenticate to see member prices.
- **Search API:** `search.costco.com/api/apps/www_costco_com/query/www_costco_com_search` — exists but CORS-opaque, can't replay without auth session.

---

## Anti-Detection Strategies

### Jitter
Random delays between actions to simulate human timing:

```bash
jitter() {
  local min_ms=$1 max_ms=$2
  local delay_ms=$((min_ms + RANDOM % (max_ms - min_ms)))
  perl -e "select(undef,undef,undef,${delay_ms}/1000)" 2>/dev/null \
    || sleep $(( (delay_ms + 999) / 1000 ))
}
```

Used between: homepage warm-up (1.5-3s), navigation (1.5-2.5s), scrolls (600-1200ms), extraction (500-1000ms).

### Homepage Warm-Up
Visit the site's homepage before the target page. Establishes cookies and a "normal" browsing pattern:

```bash
agent-browser --cdp 9222 open "https://www.example.com"
agent-browser --cdp 9222 wait --load networkidle
jitter 1500 3000
agent-browser --cdp 9222 scroll down $((150 + RANDOM % 250))
```

### Human-Like Scrolling
Multiple small scrolls with randomized distance:

```bash
for i in 1 2 3 4 5; do
  agent-browser --cdp 9222 scroll down $((250 + RANDOM % 400))
  jitter 600 1200
done
```

### Bot Detection Check
After navigation, verify the page title doesn't indicate a block:

```bash
PAGE_TITLE=$(agent-browser --cdp 9222 get title)
if echo "$PAGE_TITLE" | grep -qi "robot\|captcha\|blocked\|verify\|denied"; then
  echo "Bot detection triggered!"
  continue  # retry
fi
```

---

## Bot Detection Thresholds

### Stress Test Results (Costco, 2026-04-01)

| Phase | Requests | Delay | Pattern | Result |
|-------|----------|-------|---------|--------|
| 1 | 15 | None | 15 different queries | 15/15 OK |
| 2 | 15 | None | Same query 15x | 15/15 OK |
| 3 | 20 | None | 20 different queries | 20/20 OK |
| 4 | 25 | None | 25 different queries | 25/25 OK |
| 5 | 25 | None | 25 queries + verified product count | 24/25 OK (1 brand redirect) |
| **Total** | **100** | **None** | **Mixed** | **0 blocks** |

Average response time: ~9.5s/page (full render + networkidle).
Throughput: ~6-7 searches/minute, ~8,600/day from a single session.

### Detection by Site (Observed)

| Site | Detection System | Headless Blocked? | Headed Blocked? | Threshold |
|------|-----------------|-------------------|-----------------|-----------|
| Walmart | PerimeterX | Yes (100%) | No (with CDP trick) | Low — any `agent-browser open` triggers |
| Amazon | Custom | Yes | Occasional | Medium — works with anti-detection flags |
| Target | Akamai | Sometimes | Rare | Medium-low |
| Facebook | Custom | Unknown | No | Very high — no blocks observed |
| Costco | Akamai | Unknown | **No (100 requests)** | Very high or none for search |

---

## The Anchor Selector Pattern

The most important finding across all 5 sites: **the best extraction selector is always either a data attribute or a URL pattern, never a CSS class.**

| Site | Best Selector | Type | Why It's Stable |
|------|--------------|------|-----------------|
| Walmart | `[data-item-id]` | Data attribute | Survives CSS refactors, scopes to one card |
| Amazon | `[data-component-type="s-search-result"]` | Data attribute | Stable test identifier |
| Target | `[data-test="...ProductCardWrapper"]` | Data attribute | Explicit test anchor |
| Facebook | `a[href*="/marketplace/item/"]` | URL pattern | Permalink structure won't change |
| Costco | `a[href*=".product."]` / `data-testid` | URL + data attribute | Both stable; data-testid ideal |

**Rule:** If the site has `data-test*` or `data-*-id` attributes, use those. If it uses obfuscated class names (Facebook), fall back to URL patterns in `href`.

---

## Shell Scripting Patterns

### The Heredoc Problem

JavaScript inside bash heredocs is the #1 source of bugs. The `$` character conflicts between bash variable expansion and JavaScript regex/template literals.

**Problem:**
```bash
cat > extract.js <<JSEOF
const prices = text.match(/\$[\d,]+/g);  # \$ becomes $ (bare), JS regex breaks
const limit = $MAX;                       # $MAX expands correctly
JSEOF
```

**Solution — quoted heredoc + sed placeholder:**
```bash
cat > extract.js <<'JSEOF'
const prices = text.match(/\$[\d,]+/g);    # preserved exactly
const limit = __MAX_LISTINGS__;            # placeholder
JSEOF
sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" extract.js
```

### agent-browser eval Quoting

Never inline complex JS in `eval '...'` — shell quoting will mangle it. Always use `eval --stdin`:

```bash
# BAD — breaks on nested quotes, backslashes, $
agent-browser eval 'document.querySelectorAll("a[href*=\"/item/\"]").length'

# GOOD — pipe via stdin
echo 'document.querySelectorAll("a[href*=\"/item/\"]").length' | agent-browser eval --stdin

# BEST — file-based for complex JS
agent-browser eval --stdin < extract.js > output.json
```

### Output Unwrapping

agent-browser wraps eval output in JSON string quotes. Use Python to unwrap:

```python
import json
raw = open('output.json', encoding='utf-8').read().strip()
if raw.startswith('"'):
    raw = json.loads(raw)   # unwrap string quoting
data = json.loads(raw)      # parse actual JSON
with open('output.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

### Cleanup Pattern

Always trap EXIT to clean up Chrome and temp files:

```bash
cleanup() {
  agent-browser --cdp $CDP_PORT close 2>/dev/null || true
  taskkill //F //IM chrome.exe > /dev/null 2>&1 || true
  rm -rf "$PROFILE_DIR" 2>/dev/null || true
  rm -f "$JS_FILE" 2>/dev/null || true
  rm -f ~/.agent-browser/default.* 2>/dev/null || true
}
trap cleanup EXIT
```

---

## Common Pitfalls and Fixes

### 1. Modal/overlay blocks page
- **Facebook:** Login modal. Hide with `display: none` (don't `.remove()` — breaks React).
- **Walmart:** PerimeterX captcha. Session is dead — kill and restart with fresh profile.
- **Fix pattern:**
  ```javascript
  document.querySelectorAll('[role="dialog"]').forEach(d => d.style.display = 'none');
  document.body.style.overflow = 'auto';
  ```

### 2. Lazy-loaded content missing
Listings below the fold aren't in the DOM until scrolled into view.
- **Fix:** Scroll 4-5 times with jitter before extracting:
  ```bash
  for i in 1 2 3 4 5; do
    agent-browser --cdp 9222 scroll down $((300 + RANDOM % 400))
    jitter 600 1200
  done
  ```

### 3. Prices in separate spans
Walmart, Amazon both split prices across multiple `<span>` elements.
- **Fix:** Use `innerText` of the price container (browser concatenates for you) and regex out `$X.XX`:
  ```javascript
  const priceMatch = container.innerText.match(/\$[\d,]+\.?\d*/);
  ```

### 4. Price regex grabs title text
"Four $25 eGift Cards" has `$25` that isn't the item price.
- **Fix:** Skip price regex when `member_only` is true, or only extract from dedicated price elements.

### 5. `networkidle` hangs forever
Target and some other sites fire tracking pixels indefinitely.
- **Fix:** Use `wait --load load` then `wait "<selector>"` for the content container:
  ```bash
  agent-browser wait --load load
  agent-browser wait "[data-test='product-grid']"
  ```

### 6. Duplicate products
Some sites render the same product twice (e.g., variants, lazy-load overlap).
- **Fix:** Deduplicate by URL/ID before extraction:
  ```javascript
  const seen = new Set();
  const unique = links.filter(a => {
    const key = a.href.split('?')[0];
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  ```

---

## Proxy and Scaling

### When to add proxies

| Signal | Action |
|--------|--------|
| Single session, < 500 req/day | No proxy needed |
| Multiple parallel sessions, same IP | Residential proxy recommended |
| Datacenter/cloud server | Residential proxy required |
| Logged-in sessions at scale | Sticky residential proxy required |
| International geo-targeting | Geo-located proxy required |

### Proxy integration

```bash
# Via agent-browser flag
agent-browser --proxy "http://user:pass@gate.smartproxy.com:7777" open https://example.com

# Via Chrome launch flag
chrome --proxy-server="http://gate.brightdata.com:22225" --remote-debugging-port=9222

# Sticky session (same IP for entire login flow)
agent-browser --proxy "http://user-session-abc123:pass@gate.oxylabs.io:7777" open https://example.com
```

### Cost model

Each search page is ~500KB-1MB. At $10/GB for residential proxies:

| Volume | Data | Proxy Cost | Per-Search |
|--------|------|-----------|------------|
| 1,000 searches | ~0.75 GB | ~$7.50 | $0.0075 |
| 10,000 searches | ~7.5 GB | ~$75 | $0.0075 |
| 100,000 searches | ~75 GB | ~$750 | $0.0075 |

---

## Production Script Template

The fully-tested pattern used for Facebook Marketplace (`fb-marketplace-scrape.sh`), adapted for any site:

```bash
#!/usr/bin/env bash
# site-scrape.sh — Generic listing extractor
# Usage: ./site-scrape.sh <url> [output.json] [max_listings]

set -euo pipefail

URL="${1:?Usage: $0 <url> [output] [max]}"
OUTPUT="${2:-listings_$(date +%Y%m%d_%H%M%S).json}"
MAX_LISTINGS="${3:-10}"

CHROME_PATH="/c/Program Files/Google/Chrome/Application/chrome.exe"
CDP_PORT=9222
PROFILE_DIR="/tmp/chrome-scrape-$$"
JS_FILE="$TEMP/extract-$$.js"
RETRY_MAX=2

# Colors + helpers
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}>>>${NC} [$(date +%T)] $*"; }
ok()   { echo -e "${GREEN} ✓${NC} $*"; }
warn() { echo -e "${YELLOW} ⚠${NC} $*"; }
fail() { echo -e "${RED} ✗${NC} $*"; exit 1; }
jitter() {
  local delay_ms=$(($1 + RANDOM % ($2 - $1)))
  perl -e "select(undef,undef,undef,${delay_ms}/1000)" 2>/dev/null || sleep 1
}
ab() { agent-browser --cdp $CDP_PORT "$@" 2>&1; }

# Cleanup
cleanup() {
  ab close 2>/dev/null || true
  taskkill //F //IM chrome.exe > /dev/null 2>&1 || true
  rm -rf "$PROFILE_DIR" "$JS_FILE" ~/.agent-browser/default.* 2>/dev/null || true
}
trap cleanup EXIT

# Kill stale processes
taskkill //F //IM chrome.exe > /dev/null 2>&1 || true
rm -f ~/.agent-browser/default.* 2>/dev/null || true
sleep 2

START_TIME=$(date +%s)

# Retry loop
attempt=0
while [ $attempt -lt $RETRY_MAX ]; do
  attempt=$((attempt + 1))
  PROFILE_DIR="/tmp/chrome-scrape-$(date +%s)-$attempt"
  [ $attempt -gt 1 ] && { taskkill //F //IM chrome.exe > /dev/null 2>&1 || true; jitter 1500 3000; }

  # 1. Launch Chrome
  "$CHROME_PATH" --remote-debugging-port=$CDP_PORT --user-data-dir="$PROFILE_DIR" \
    --no-first-run --no-default-browser-check --disable-blink-features=AutomationControlled \
    "about:blank" &
  sleep 4

  # 2. Warm up
  jitter 800 1500
  ab open "https://SITE_HOMEPAGE" || continue
  ab wait --load networkidle || true
  jitter 1500 3000
  ab scroll down $((150 + RANDOM % 250))

  # 3. Navigate
  ab open "$URL" || continue
  ab wait --load networkidle || true
  jitter 1500 2500

  # 4. Bot check
  TITLE=$(ab get title)
  echo "$TITLE" | grep -qi "blocked\|captcha\|robot\|denied" && continue

  # 5. Handle overlays (site-specific)
  # ab eval '...'

  # 6. Scroll
  for i in 1 2 3 4 5; do ab scroll down $((250 + RANDOM % 400)); jitter 600 1200; done

  # 7. Extract (quoted heredoc + sed for MAX_LISTINGS)
  cat > "$JS_FILE" <<'JSEOF'
  // ... site-specific extraction JS with __MAX_LISTINGS__ placeholder ...
JSEOF
  sed -i "s/__MAX_LISTINGS__/$MAX_LISTINGS/g" "$JS_FILE"
  ab eval --stdin < "$JS_FILE" > "$OUTPUT" 2>/dev/null

  # 8. Validate + pretty-print
  [ $(wc -c < "$OUTPUT") -lt 100 ] && continue
  EXTRACTED=$(python -c "
import json, sys
raw = open(sys.argv[1], encoding='utf-8').read().strip()
if raw.startswith('\"'): raw = json.loads(raw)
data = json.loads(raw)
with open(sys.argv[1], 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print(data['metadata']['extracted'])
" "$OUTPUT" 2>/dev/null || echo "?")

  # 9. Report
  echo "Extracted: $EXTRACTED listings in $(($(date +%s) - START_TIME))s"
  exit 0
done

echo "Failed after $RETRY_MAX attempts."
exit 1
```

---

## Files Reference

### Analysis Reports
| File | Site | Date |
|------|------|------|
| `extraction-analysis.md` | Walmart | 2026-03-29 |
| `COMPARISON_REPORT.md` | Amazon | 2026-03-31 |
| `TARGET_COMPARISON_REPORT.md` | Target | 2026-03-31 |
| `fb-marketplace-analysis.md` | Facebook | 2026-04-01 |
| `costco-analysis.md` | Costco | 2026-04-01 |

### Production Scripts
| File | Site | Features |
|------|------|----------|
| `walmart-extract.sh` | Walmart | CDP, jitter, retry, `[data-item-id]` |
| `amazon-scrape.sh` | Amazon | CDP, jitter, warm-up, `[data-component-type]`, 17-field extraction |
| `target-extract.sh` | Target | CDP, jitter, `[data-test]`, `load` wait strategy |
| `fb-marketplace-scrape.sh` | Facebook | CDP, jitter, modal hide, URL-pattern selector |

### Instruction Docs
| File | Purpose |
|------|---------|
| `walmart-extraction-steps.md` | Bulletproof Walmart steps (PerimeterX workaround) |
| `ws.md` | Walmart phones-only quick script |
| `tokanalysis.md` | Token analysis for compact instruction format |

### Raw Method Outputs (per site)
Each site has `m1_snapshot.txt`, `m2_text.txt`, `m3_screenshot.png`, `m4_dom.json`, `m5_scoped.txt`, `m6_*.json` — the raw outputs from each extraction method test.
