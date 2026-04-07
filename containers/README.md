# Barkain — Scraper Containers

Each retailer runs in its own Docker container with Chromium, agent-browser CLI, and a FastAPI server. The backend dispatches `POST /extract` requests to containers and receives structured JSON responses.

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
