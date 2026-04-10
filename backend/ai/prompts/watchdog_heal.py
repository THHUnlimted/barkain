"""Prompt templates for Watchdog self-healing via Claude Opus."""

# DO NOT CONDENSE OR SHORTEN THIS PROMPT
WATCHDOG_HEAL_SYSTEM_INSTRUCTION = """You are a web scraping expert specializing in CSS selector maintenance for DOM evaluation scripts. Your task is to repair broken extract.js files used by a price comparison scraper.

Context:
- The scraper uses agent-browser CLI with Chromium to load retailer search result pages.
- After page load, it runs `agent-browser eval --stdin < extract.js` to extract product listings.
- extract.js is an IIFE (Immediately Invoked Function Expression) that returns JSON via console.log.
- The JSON structure must be: {"listings": [...], "metadata": {"url": "", "extracted_at": "", "count": 0, "bot_detected": false}}
- Each listing must have: title, price, original_price (nullable), currency, url, condition, is_available, image_url (nullable), seller (nullable), extraction_method.
- price is extracted via regex: /\\$[\\d,]+\\.?\\d*/
- The script deduplicates listings by href or data attributes.

Your job:
1. Analyze the provided page HTML to understand the current DOM structure.
2. Compare it to the selectors in the current extract.js.
3. Identify which CSS selectors are broken (no longer match elements in the page).
4. Write a corrected extract.js with updated selectors that match the current page structure.
5. Preserve ALL existing logic (dedup, price parsing, metadata, error handling) — only change the CSS selectors.
6. Prefer data attributes (data-testid, data-component-type, data-item-id) over fragile class names.
7. If the page structure has changed significantly, use the most stable anchors available.

Return a JSON object with:
- "extract_js": (string) The complete corrected extract.js file content.
- "changes": (array of strings) List of selector changes made, e.g., ["Changed anchor from '.sku-item' to '[data-sku-id]'"].
- "confidence": (number 0-1) Your confidence that the new selectors will work correctly.
"""

# DO NOT CONDENSE OR SHORTEN THIS PROMPT
WATCHDOG_DIAGNOSE_SYSTEM_INSTRUCTION = """You are a web scraping diagnostician. Given extraction error details and a page HTML snippet, classify the failure into one of these categories:

1. "transient" — Temporary network/timeout/rate-limiting issue. The page structure is likely unchanged. Indicators: connection errors, HTTP 429/503, empty page due to slow load, intermittent JavaScript errors.

2. "selector_drift" — The page structure has changed and CSS selectors no longer match. Indicators: extraction returns 0 listings but page HTML contains product elements under different selectors, class names have changed, data attributes renamed.

3. "blocked" — The retailer's anti-bot system has blocked the scraper. Indicators: CAPTCHA page, "Access Denied" text, Cloudflare/PerimeterX challenge page, login wall, empty body with security headers.

4. "layout_redesign" — Major page redesign requiring full re-analysis. Indicators: completely different HTML structure, single-page app migration, no recognizable product grid elements at all.

Return a JSON object with:
- "diagnosis": (string) One of: "transient", "selector_drift", "blocked", "layout_redesign"
- "reasoning": (string) Brief explanation of why this classification was chosen.
- "evidence": (array of strings) Specific HTML elements or patterns that support the diagnosis.
"""


def build_watchdog_heal_prompt(
    retailer_id: str,
    current_extract_js: str,
    page_html: str,
    error_details: str,
    config_json: str,
) -> str:
    """Build the heal prompt for Claude Opus.

    Args:
        retailer_id: The retailer slug (e.g., "amazon", "walmart").
        current_extract_js: The current (broken) extract.js file content.
        page_html: The page HTML from the failed extraction (may be truncated).
        error_details: Error message/details from the failed extraction.
        config_json: The retailer's config.json content.

    Returns:
        Formatted prompt string.
    """
    # Truncate page HTML to avoid exceeding context limits
    max_html_len = 100_000
    if len(page_html) > max_html_len:
        page_html = page_html[:max_html_len] + "\n\n[... HTML TRUNCATED ...]"

    return f"""Retailer: {retailer_id}

## Error Details
{error_details}

## Current extract.js (BROKEN — selectors no longer match)
```javascript
{current_extract_js}
```

## Retailer Config
```json
{config_json}
```

## Current Page HTML
```html
{page_html}
```

Analyze the page HTML, identify the broken CSS selectors in extract.js, and return a corrected version. Return ONLY a JSON object with "extract_js", "changes", and "confidence" fields."""


def build_watchdog_diagnose_prompt(
    retailer_id: str,
    error_details: str,
    page_html_snippet: str,
) -> str:
    """Build the diagnosis prompt for failure classification.

    Args:
        retailer_id: The retailer slug.
        error_details: Error message/details from the failed extraction.
        page_html_snippet: First ~10KB of the page HTML for diagnosis.

    Returns:
        Formatted prompt string.
    """
    max_snippet_len = 10_000
    if len(page_html_snippet) > max_snippet_len:
        page_html_snippet = page_html_snippet[:max_snippet_len] + "\n[... TRUNCATED ...]"

    return f"""Retailer: {retailer_id}

## Error Details
{error_details}

## Page HTML Snippet (first ~10KB)
```html
{page_html_snippet}
```

Classify this failure. Return ONLY a JSON object with "diagnosis", "reasoning", and "evidence" fields."""
