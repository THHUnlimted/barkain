"""Prompt template for UPC-to-product resolution via Gemini API."""


def build_upc_lookup_prompt(upc: str) -> str:
    """Build a prompt that asks Gemini to resolve a UPC barcode to product data.

    Args:
        upc: A 12 or 13 digit UPC/EAN barcode string.

    Returns:
        Formatted prompt string requesting JSON output.
    """
    return (
        "You are a product database lookup assistant. "
        "Given a UPC/EAN barcode, return the product information "
        "in JSON format.\n\n"
        f"UPC: {upc}\n\n"
        "Return ONLY a JSON object with these fields "
        "(no markdown, no explanation):\n"
        "{\n"
        '    "name": "Full product name",\n'
        '    "brand": "Brand name",\n'
        '    "category": "Product category '
        '(e.g., Electronics, Kitchen Appliances, Smart Home)",\n'
        '    "description": "Brief product description (1-2 sentences)",\n'
        '    "asin": "Amazon ASIN if known, or null",\n'
        '    "image_url": "Product image URL if known, or null"\n'
        "}\n\n"
        "If you cannot identify the product from this UPC, return:\n"
        '{"error": "unknown_upc"}'
    )
