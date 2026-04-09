"""Prompt template for UPC-to-product resolution via Gemini API."""

UPC_LOOKUP_SYSTEM_INSTRUCTION = """Research the provided UPC (Universal Product Code) and return a JSON object with a detailed reasoning field and the most specific electronic device name associated with the code. Your output must include, if available, full retail identifiers such as brand, product line, model/specification, size, and model or SKU/part number in parentheses (e.g., "Apple MacBook Air 13-inch model (MDHG4LL/A)"). Maintain optimization instructions for lookup speed: use the minimum possible number of data sources, prioritize the fastest and highest-yield databases, and explain how you maximize speed and accuracy at every step.
Begin with a stepwise, detailed explanation in the "reasoning" field of all actions taken to optimize lookup speed, including database/source selection, methods to identify electronics-only UPCs, and how you verify product specificity.
In your reasoning, state how you determined which full identifiers are available (brand, model, size, SKU, etc.), and why the name is as specific as possible.
If the UPC cannot be matched to an electronics device, is invalid, or if the needed specificity cannot be determined, explain this in your reasoning and set "device_name" to null.
Return a JSON object with:
"device_name": (string or null) The most fully specified name available for the device: must include brand, product line, specification or size, and model/part/SKU if these are available. If a match is not found or not specific, return null.
Step 1: Validate UPC format and electronics relevance for speed. Step 2: Query high-yield electronics UPC/retail databases with maximum reliability and speed (vendor/brand-agnostic but electronics-focused). Step 3: Cross-verify matched item across multiple sources to confirm specificity (brand, product line, model/SKU, size). Step 4: If feeds consistently return a full retail name (brand, line, size, model/SKU), extract the most precise naming available; otherwise, default to null. Step 5: Given the UPC provided, identify the associated electronics item and confirm its exact product name and SKU across reputable sources (e.g., manufacturer repos, major retailers, or authorized resellers). Step 6: Assemble the final, fully specified device_name in the required format: Brand Product Line/Type Size/Specification (Model or SKU). Step 7: Provide justification for why this is the most specific identifier achievable from the sources and note any alternative naming variants observed to ensure traceability. Step 8: Ensure sources are electronics-focused and minimize the number of data sources to preserve lookup speed while maintaining accuracy. Step 9: If no specific model/SKU is verifiable, set device_name to null and explain why."""


def build_upc_lookup_prompt(upc: str) -> str:
    """Build a prompt that asks Gemini to resolve a UPC barcode to product data.

    Args:
        upc: A 12 or 13 digit UPC/EAN barcode string.

    Returns:
        Formatted prompt string requesting JSON output.
    """
    return f"""{upc}

Return ONLY a JSON object with ONE field:
- "device_name": (string or null)

Do not include reasoning or any other fields in the output. Only return {{"device_name": "..."}} or {{"device_name": null}}."""
