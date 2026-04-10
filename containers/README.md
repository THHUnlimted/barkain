# Barkain — Scraper Containers

Each retailer runs in its own Docker container with Chromium, agent-browser CLI, and a FastAPI server. The backend dispatches `POST /extract` requests to containers and receives structured JSON responses.

> **Shared Base Image (Step 2a):** All retailer containers inherit from `barkain-base:latest` (`containers/base/`). The base provides Chromium, Xvfb, agent-browser, FastAPI server, and entrypoint. Retailer containers only add their extraction scripts.

## Architecture

```
┌────────────────────────────────────────┐
│  Container (per retailer)              │
│  ├── Xvfb (virtual display :99)        │
│  ├── Chromium (headed, anti-detection) │
│  ├── agent-browser CLI (DOM eval)      │
│  ├── FastAPI server (port 8080)        │
│  │   ├── GET  /health                  │
│  │   └── POST /extract                 │
│  ├── base-extract.sh (9-step pattern)  │
│  ├── extract.js (DOM eval script)      │
│  ├── config.json (selectors, rates)    │
│  └── test_fixtures.json                │
└────────────────────────────────────────┘
```

## Template

`containers/template/` contains the base files all retailer containers inherit from:

| File | Purpose |
|------|---------|
| `Dockerfile` | Base image: Node 20 + Chromium + Python/FastAPI + Xvfb |
| `server.py` | FastAPI app with `/health` and `/extract` endpoints |
| `entrypoint.sh` | Starts Xvfb then uvicorn |
| `base-extract.sh` | 9-step extraction skeleton with placeholders |
| `extract.js.example` | DOM eval JavaScript template |
| `config.json.example` | Retailer config schema (selectors, rate limits, anti-detection) |
| `test_fixtures.json.example` | Test queries with expected outputs |

## Creating a Retailer Container

1. Copy the template:
   ```bash
   cp -r containers/template containers/walmart
   ```

2. Customize:
   - Replace placeholders in `base-extract.sh` (`__SITE_HOMEPAGE__`, `__SEARCH_URL_TEMPLATE__`, `__ANCHOR_SELECTOR__`)
   - Write site-specific `extract.js`
   - Fill in `config.json` with real selectors
   - Add test fixtures with known products

3. Build:
   ```bash
   docker build -t barkain-scraper-walmart ./containers/walmart
   ```

4. Run:
   ```bash
   docker run -p 8083:8080 -e RETAILER_ID=walmart barkain-scraper-walmart
   ```

5. Test:
   ```bash
   # Health check
   curl http://localhost:8083/health

   # Extract
   curl -X POST http://localhost:8083/extract \
     -H "Content-Type: application/json" \
     -d '{"query": "Samsung 65 inch TV", "max_listings": 5}'
   ```

## Port Assignments

| Port | Retailer |
|------|----------|
| 8081 | Amazon |
| 8082 | Best Buy |
| 8083 | Walmart |
| 8084 | Target |
| 8085 | Home Depot |
| 8086 | Lowe's |
| 8087 | eBay (new) |
| 8088 | eBay (used/refurb) |
| 8089 | Sam's Club |
| 8090 | BackMarket |
| 8091 | Facebook Marketplace |

## Batch 1 Retailers (Step 1d)

Five containers built and ready for testing:

| Retailer | Directory | Build & Run |
|----------|-----------|-------------|
| Amazon | `containers/amazon/` | `docker build -t barkain-amazon ./containers/amazon && docker run -p 8081:8080 -e RETAILER_ID=amazon barkain-amazon` |
| Walmart | `containers/walmart/` | `docker build -t barkain-walmart ./containers/walmart && docker run -p 8083:8080 -e RETAILER_ID=walmart barkain-walmart` |
| Target | `containers/target/` | `docker build -t barkain-target ./containers/target && docker run -p 8084:8080 -e RETAILER_ID=target barkain-target` |
| Sam's Club | `containers/sams_club/` | `docker build -t barkain-sams-club ./containers/sams_club && docker run -p 8089:8080 -e RETAILER_ID=sams_club barkain-sams-club` |
| FB Marketplace | `containers/fb_marketplace/` | `docker build -t barkain-fb-marketplace ./containers/fb_marketplace && docker run -p 8091:8080 -e RETAILER_ID=fb_marketplace barkain-fb-marketplace` |

### Retailer-Specific Notes

- **Walmart (PerimeterX):** NEVER use `agent-browser open` for navigation. Chrome must launch directly with the search URL as its starting page. The extract.sh skips the warm-up step entirely and passes `$SEARCH_URL` to Chromium instead of `about:blank`.
- **Target (analytics hang):** Use `ab wait --load load` instead of `networkidle`. Target's analytics pixels fire indefinitely. After load, wait for `[data-test='product-grid']` selector.
- **Facebook Marketplace (login modal):** Hide the login modal with `display:none` via CSS. NEVER use `.remove()` — it breaks React's virtual DOM. The DOM is fully rendered behind the CSS overlay.
- **Sam's Club (unvalidated selectors):** Anchor selectors are best-guess based on Walmart patterns. Needs live testing to confirm. config.json has `"anchor_status": "needs_validation"`.

## Batch 2 Retailers (Step 1e)

Six additional containers:

| Retailer | Directory | Port | Key Notes |
|----------|-----------|------|-----------|
| Best Buy | `containers/best_buy/` | 8082 | `.sku-item` anchor, standard flow |
| Home Depot | `containers/home_depot/` | 8085 | `[data-testid="product-pod"]`, needs validation |
| Lowe's | `containers/lowes/` | 8086 | Multi-fallback selectors, needs validation |
| eBay (new) | `containers/ebay_new/` | 8087 | Same site as eBay Used but with `LH_ItemCondition=1000` filter |
| eBay (used/refurb) | `containers/ebay_used/` | 8088 | Condition filter for used+refurb, extracts condition text (used/refurbished/open_box) |
| BackMarket | `containers/backmarket/` | 8090 | Refurbished marketplace — all items default to condition "refurbished", includes seller/grade |

### eBay Condition Separation
eBay new and used run as **separate containers** to keep extraction simple. Each uses different URL parameters to filter by condition at the eBay search level, so the container only receives items of the correct condition.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RETAILER_ID` | `template` | Retailer identifier |
| `SCRIPT_VERSION` | `0.0.0` | Extraction script version |
| `CHROMIUM_PATH` | `/usr/bin/chromium` | Path to Chromium binary |
| `DISPLAY` | `:99` | Xvfb display number |

## API Contract

### `GET /health`

```json
{
  "status": "healthy",
  "retailer_id": "walmart",
  "script_version": "0.1.0",
  "chromium_ready": true
}
```

### `POST /extract`

**Request:**
```json
{
  "query": "Samsung 65 inch TV",
  "product_name": "Samsung 65\" Class QLED 4K TV",
  "upc": "887276123456",
  "max_listings": 10
}
```

**Response (success):**
```json
{
  "retailer_id": "walmart",
  "query": "Samsung 65 inch TV",
  "extraction_time_ms": 4523,
  "listings": [
    {
      "title": "Samsung 65\" QLED 4K Smart TV",
      "price": 697.99,
      "original_price": 999.99,
      "currency": "USD",
      "url": "https://www.walmart.com/ip/...",
      "condition": "new",
      "is_available": true,
      "image_url": "https://...",
      "seller": null,
      "extraction_method": "dom_eval"
    }
  ],
  "metadata": {
    "url": "https://www.walmart.com/search?q=...",
    "extracted_at": "2026-04-07T12:00:00Z",
    "script_version": "0.1.0",
    "bot_detected": false
  },
  "error": null
}
```

**Response (error):**
```json
{
  "retailer_id": "walmart",
  "query": "Samsung 65 inch TV",
  "extraction_time_ms": -1,
  "listings": [],
  "metadata": { "extracted_at": "...", "bot_detected": true },
  "error": {
    "code": "EXTRACTION_FAILED",
    "message": "Bot detection triggered after 2 retries",
    "details": {}
  }
}
```
