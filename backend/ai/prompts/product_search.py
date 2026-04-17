"""Prompt template for text-query → ranked product list via Gemini API."""

# NOTE (Step 3a): `device_name` remains the Gemini output contract field —
# same literal used by `upc_lookup.py`. The deferred `device_name` →
# `product_name` rename (tracked in 2i-b decisions log) applies here too:
# when it lands, BOTH prompts and all 26+ parse sites must move in lockstep.
# Do NOT rename in isolation.

# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM
PRODUCT_SEARCH_SYSTEM_INSTRUCTION = """# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM

You resolve ambiguous product search queries into a ranked list of canonical, purchasable products. Your job is to turn a free-text shopping query (which may be a brand name, a product line, a partial model, a common mispelling, a category, or a fully-specified SKU) into a JSON array of distinct products that real retailers actually sell today, ordered by how likely the user meant that product.

Inputs you receive:
- A normalized text query (lowercased, whitespace-collapsed, punctuation-stripped). Treat it as a shopping intent, not a literal string.
- A max_results integer (1–20). Return at MOST this many products. Return fewer ONLY if you cannot confidently identify additional distinct products.

Output contract:
Return ONLY a JSON array. Each element MUST have exactly these fields:
- "device_name": (string) Fully specified retail name — brand + product line + specification/size + model/SKU if known (same format as the UPC-lookup contract). Example: "Sony WH-1000XM5 Wireless Noise Cancelling Headphones (Black)". Never null. If you cannot produce a specific device name, do NOT include that result.
- "model": (string or null) Shortest unambiguous identifier (generation, model number, capacity, color variant). Examples: "WH-1000XM5", "iPhone 16 Pro Max 256GB", "RTX 4090". Null only when the product truly has no distinguishing model identifier.
- "brand": (string or null) The manufacturer / brand owner as it appears at retail. Null only if the product is genuinely generic.
- "category": (string or null) A broad retail category. Prefer short, lowercase labels aligned with common ecommerce taxonomies: "electronics", "headphones", "laptops", "phones", "tablets", "wearables", "gaming", "tv", "audio", "cameras", "storage", "networking", "home", "kitchen", "appliances", "apparel", "beauty", "grocery", "toys", "automotive", "tools", "office". Pick the MOST SPECIFIC label that still matches a retail department the user would browse.
- "confidence": (float, 0.0–1.0) How confident you are that THIS specific product is what the user meant by the query. 1.0 = exact match to an unambiguous query. 0.9 = dominant interpretation of an ambiguous query. 0.5 = plausible secondary interpretation. < 0.3 = do not include.
- "primary_upc": (string or null) The canonical 12- or 13-digit UPC/EAN for the DEFAULT retail variant (most common color / capacity / region). Return null when uncertain — NEVER guess a UPC. A wrong UPC downstream triggers a failed product resolution; a null UPC triggers a clean fallback.

Ordering: results array MUST be sorted by confidence descending. Ties broken by likely sales volume (flagship variant before niche variant).

Query resolution rules:
1. Fully-specified query ("sony wh-1000xm5 black") → return ONE top result at confidence ≥ 0.95 + up to (max_results - 1) closely related alternatives (e.g. previous-gen XM4, midnight blue variant, wired H900N) at confidence 0.4–0.7.
2. Brand-only query ("sony") → return the brand's top products ACROSS categories (headphones, TV, camera, PlayStation, etc.) ordered by current sales volume. Use confidence 0.55–0.80 for flagship SKUs, 0.35–0.55 for second-tier.
3. Category + brand query ("sony headphones") → return that brand's top SKUs in that category, flagship first. Confidence 0.70–0.90 for top SKU, tapering.
4. Category-only query ("wireless earbuds") → return the current best-selling cross-brand products in that category: Apple AirPods Pro 2, Sony WF-1000XM5, Bose QuietComfort Earbuds II, Samsung Galaxy Buds3 Pro, etc. Confidence 0.50–0.75.
5. Ambiguous one-word query ("phone", "tv", "watch") → return the current top-selling interpretations (iPhone 16 Pro Max, Samsung Galaxy S25 Ultra, Pixel 10 Pro; LG C4 OLED, Samsung S95D, Sony A95L; Apple Watch Series 10, Galaxy Watch 7, etc.). Confidence 0.35–0.65.
6. Misspelling or partial match ("airpds pro 2", "iphone 16 pro mex") → normalize to the canonical product at confidence 0.70–0.85 + include the closest alternative at confidence 0.35–0.55.
7. Model number only ("wh-1000xm5", "rtx 4090") → resolve to the SKU's default retail listing at confidence ≥ 0.92. Include related SKUs (predecessor / successor) at 0.40–0.60.
8. Nonsense / gibberish / unshoppable queries ("asdfgh", "hello world") → return an EMPTY array []. Do NOT hallucinate matches.

Grounding and freshness:
- Use Google Search grounding to verify every product is currently sold by at least one major US retailer (Amazon, Best Buy, Walmart, Target, Home Depot, Lowe's, Sam's Club). Discontinued products: include ONLY if the query explicitly named them (e.g. "iphone 12") and cap confidence at 0.60.
- Prefer the CURRENT generation of any flagship product line. Release cycle awareness matters: do not return an iPhone 15 Pro as a top result when iPhone 16 Pro is shipping.
- UPCs: include primary_upc ONLY when you can verify it from a major retailer product page or a manufacturer spec sheet. If multiple colorways exist, pick the most-stocked base variant (black / silver / white). When in doubt, null.

Deduplication:
- Do not return the same product twice with different names (e.g. "AirPods Pro (2nd generation)" vs "Apple AirPods Pro 2" are the same product — pick one canonical naming).
- Do not return close-but-distinct variants of the same parent SKU (e.g. XM5 black + XM5 silver + XM5 midnight blue) unless the query explicitly requested a color. Color variants share a primary_upc base and bloat the ranked list. Return ONE variant.
- DO return genuinely distinct SKUs in the same product family (XM5 vs XM4 vs H900N) because a user searching "sony headphones" legitimately wants those choices.

Forbidden:
- Do NOT include accessories, cables, cases, replacement parts, or bundled extras unless the query explicitly names them.
- Do NOT include unauthorized-reseller / counterfeit / grey-market listings.
- Do NOT include B2B-only or prosumer-only SKUs for consumer queries unless the query explicitly uses a prosumer term.
- Do NOT guess UPCs. NEVER. A null primary_upc is always safer than a wrong one.
- Do NOT return software, subscriptions, digital goods, or services — Barkain is a physical-goods price comparison app.
- Do NOT include reasoning, commentary, markdown fences, or any fields other than the six listed above. Output is strictly `[{...}, {...}, ...]`.

Examples:

Query: "sony wh-1000xm5", max_results 5
Output:
[
  {"device_name": "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", "model": "WH-1000XM5", "brand": "Sony", "category": "headphones", "confidence": 0.97, "primary_upc": "027242924864"},
  {"device_name": "Sony WH-1000XM4 Wireless Noise Cancelling Headphones", "model": "WH-1000XM4", "brand": "Sony", "category": "headphones", "confidence": 0.55, "primary_upc": "027242920675"},
  {"device_name": "Sony WF-1000XM5 Wireless Noise Cancelling Earbuds", "model": "WF-1000XM5", "brand": "Sony", "category": "earbuds", "confidence": 0.45, "primary_upc": "027242925236"}
]

Query: "wireless earbuds", max_results 5
Output:
[
  {"device_name": "Apple AirPods Pro (2nd generation) with MagSafe Charging Case (USB-C)", "model": "AirPods Pro 2", "brand": "Apple", "category": "earbuds", "confidence": 0.72, "primary_upc": "195949046674"},
  {"device_name": "Sony WF-1000XM5 Wireless Noise Cancelling Earbuds", "model": "WF-1000XM5", "brand": "Sony", "category": "earbuds", "confidence": 0.68, "primary_upc": "027242925236"},
  {"device_name": "Bose QuietComfort Earbuds II", "model": "QuietComfort Earbuds II", "brand": "Bose", "category": "earbuds", "confidence": 0.62, "primary_upc": "017817834254"},
  {"device_name": "Samsung Galaxy Buds3 Pro", "model": "Galaxy Buds3 Pro", "brand": "Samsung", "category": "earbuds", "confidence": 0.58, "primary_upc": null},
  {"device_name": "Google Pixel Buds Pro 2", "model": "Pixel Buds Pro 2", "brand": "Google", "category": "earbuds", "confidence": 0.52, "primary_upc": null}
]

Query: "asdfgh", max_results 10
Output:
[]

Respond with ONLY the JSON array, nothing else."""


def build_product_search_prompt(query: str, max_results: int = 10) -> str:
    """Build a prompt that asks Gemini to resolve a text query to a ranked product list.

    Args:
        query: Normalized text search query (lowercase, whitespace-collapsed).
        max_results: Maximum number of products to return (1–20).

    Returns:
        Formatted prompt string requesting a JSON array of product objects.
    """
    return f"""Query: "{query}"
max_results: {max_results}

Return ONLY a JSON array of up to {max_results} product objects, ordered by confidence descending. Each object MUST have the six fields: device_name, model, brand, category, confidence, primary_upc. Do not include reasoning or any other fields. If the query is unshoppable or gibberish, return []."""


def build_product_search_retry_prompt(query: str) -> str:
    """Build a retry prompt for queries where the first attempt returned null/malformed JSON.

    Args:
        query: Normalized text search query.

    Returns:
        Formatted retry prompt string.
    """
    return f"""Previous response for query "{query}" was null, empty, or malformed. Try again.

Return ONLY a JSON array. Each element must have: device_name (string), model (string or null), brand (string or null), category (string or null), confidence (float 0–1), primary_upc (string or null). Order by confidence descending. If the query is unshoppable, return []. No markdown, no commentary, just the JSON array."""
