"""Prompt template for UPC-to-product resolution via Gemini API."""

# NOTE (Step 2i-b): a rename of `device_name` → `product_name` was considered
# in this hardening sweep and DEFERRED. `device_name` is the literal Gemini
# output contract field — it appears in the system instruction below
# (verbatim, do not edit), in `build_upc_lookup_prompt`, in
# `build_upc_retry_prompt`, in `m1_product/service.py` (5 parse sites), and
# in 13+ test assertions across `backend/tests/`. A mechanical rename would
# require coordinated prompt + service-parse + test updates and risks
# breaking the LLM contract during a hardening step that isn't supposed
# to change behavior. Audit count at 2i-b: 26 backend occurrences across 9
# files, 0 iOS occurrences (the iOS-facing `ProductResponse` schema already
# uses `name`). Track in Phase 3 if still desired.

# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM
UPC_LOOKUP_SYSTEM_INSTRUCTION = """# DO NOT CONDENSE OR SHORTEN THIS PROMPT — COPY VERBATIM

Research the provided UPC (Universal Product Code) and return a JSON object with a detailed reasoning field and the most specific electronic device name associated with the code. Your output must include, if available, full retail identifiers such as brand, product line, model/specification, size, and model or SKU/part number in parentheses (e.g., "Apple MacBook Air 13-inch model (MDHG4LL/A)") Additionally, Return model: the shortest unambiguous product identifier including generation, model number, capacity, and color variant where applicable.
Examples:
  - "iPad Pro 13-inch M4 256GB" not "iPad Pro"
  - "Galaxy Buds Pro (1st Gen)" not "Galaxy Buds Pro"
  - "RTX 4090" not "GeForce RTX 4090 Founders Edition"
  - "iPhone 16 Pro Max 256GB" not "iPhone 16 Pro Max".
Maintain optimization instructions for lookup speed: use the minimum possible number of data sources, prioritize the fastest and highest-yield databases, and explain how you maximize speed and accuracy at every step.
Begin with a stepwise, detailed explanation in the "reasoning" field of all actions taken to optimize lookup speed, including database/source selection, methods to identify electronics-only UPCs, and how you verify product specificity.
In your reasoning, state how you determined which full identifiers are available (brand, model, size, SKU, etc.), and why the name is as specific as possible.
If the UPC cannot be matched to an electronics device, is invalid, or if the needed specificity cannot be determined, explain this in your reasoning and set "device_name" to null.
Return a JSON object with:
"device_name": (string or null) The most fully specified name available for the device: must include brand, product line, specification or size, and model/part/SKU if these are available. If a match is not found or not specific, return null.
"model": (string or null) The shortest unambiguous product identifier including generation, model number, capacity, and color variant where applicable. Examples: "iPad Pro 13-inch M4 256GB", "Galaxy Buds Pro (1st Gen)", "RTX 4090", "iPhone 16 Pro Max 256GB". If no model can be determined, return null.
"reasoning": (string) Your step-by-step explanation.
Step 1: Validate UPC format and electronics relevance for speed. Step 2: Query high-yield electronics UPC/retail databases with maximum reliability and speed (vendor/brand-agnostic but electronics-focused). Step 3: Cross-verify matched item across multiple sources to confirm specificity (brand, product line, model/SKU, size). Step 4: If feeds consistently return a full retail name (brand, line, size, model/SKU), extract the most precise naming available; otherwise, default to null. Step 5: Given the UPC provided, identify the associated electronics item and confirm its exact product name and SKU across reputable sources (e.g., manufacturer repos, major retailers, or authorized resellers). Step 6: Assemble the final, fully specified device_name in the required format: Brand Product Line/Type Size/Specification (Model or SKU). Step 7: Provide justification for why this is the most specific identifier achievable from the sources and note any alternative naming variants observed to ensure traceability. Step 8: Ensure sources are electronics-focused and minimize the number of data sources to preserve lookup speed while maintaining accuracy. Step 9: If no specific model/SKU is verifiable, set device_name to null and explain why."""


def build_upc_lookup_prompt(upc: str) -> str:
    """Build a prompt that asks Gemini to resolve a UPC barcode to product data.

    Args:
        upc: A 12 or 13 digit UPC/EAN barcode string.

    Returns:
        Formatted prompt string requesting JSON output with device_name + model.
    """
    return f"""{upc}

Return ONLY a JSON object with TWO fields:
- "device_name": (string or null) — most fully specified product name
- "model": (string or null) — shortest unambiguous identifier (generation, model number, capacity, color)

Do not include reasoning or any other fields in the output. Only return {{"device_name": "...", "model": "..."}} or {{"device_name": null, "model": null}}."""


def build_upc_retry_prompt(upc: str) -> str:
    """Build a retry prompt for UPCs that returned null on first attempt.

    Uses broader search language to encourage checking non-electronics databases.

    Args:
        upc: A 12 or 13 digit UPC/EAN barcode string.

    Returns:
        Formatted retry prompt string.
    """
    return f"""The UPC {upc} was not identified on the first attempt. Try broader databases including non-electronics sources (grocery, household, apparel, toys, automotive). Search UPCitemdb, Open Food Facts, barcodelookup.com, and major retailer product feeds.

Return ONLY a JSON object with TWO fields:
- "device_name": (string or null) — most fully specified product name
- "model": (string or null) — shortest unambiguous identifier (generation, model number, capacity, color)

Do not include reasoning or any other fields in the output. Only return {{"device_name": "...", "model": "..."}} or {{"device_name": null, "model": null}}."""
