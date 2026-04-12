// Amazon extraction — DOM eval for search results.
// Anchor: [data-component-type="s-search-result"] with data-asin attribute.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Title fallback chain (Step 2b — SP-9 fix):
//   1. [data-cy="title-recipe"] span — most reliable when present
//   2. h2 a .a-text-normal — standard layout
//   3. h2 a span — older layout
//   4. img[data-image-latency="s-product-image"] alt — image alt
//   5. img.s-image alt — generic product image
//   Brand-name validation: if title is too short (single word / <20 chars),
//   keep trying — it's likely just the brand label, not the full product name.
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all search result cards
  const cards = document.querySelectorAll('[data-component-type="s-search-result"]');

  // 2. Deduplicate by ASIN
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const asin = el.getAttribute('data-asin');
    if (!asin || seen.has(asin)) return false;
    seen.add(asin);
    return true;
  });

  // Sponsored noise patterns to strip from titles
  const SPONSORED_NOISE = [
    /Sponsored\s*/gi,
    /You're seeing this ad based on the product's relevance to your search query\.?\s*/gi,
    /Leave ad feedback\s*/gi,
    /You're seeing this ad\s*/gi
  ];

  function cleanTitle(text) {
    let cleaned = text;
    for (const pattern of SPONSORED_NOISE) {
      cleaned = cleaned.replace(pattern, '');
    }
    return cleaned.trim();
  }

  // Title selector chain — try each in order, prefer substantive titles
  const TITLE_SELECTORS = [
    el => el.querySelector('[data-cy="title-recipe"] span')?.innerText?.trim(),
    el => el.querySelector('h2 a .a-text-normal')?.innerText?.trim(),
    el => el.querySelector('h2 a span')?.innerText?.trim(),
    el => el.querySelector('img[data-image-latency="s-product-image"]')?.alt?.trim(),
    el => el.querySelector('img.s-image')?.alt?.trim(),
  ];

  function extractTitle(el) {
    let fallback = '';
    for (const selector of TITLE_SELECTORS) {
      const candidate = selector(el);
      if (!candidate || candidate.length < 3) continue;

      // Accept immediately if it looks like a full product name
      const wordCount = candidate.split(/\s+/).length;
      if (wordCount >= 3 || candidate.length > 20) {
        return cleanTitle(candidate);
      }
      // Keep as fallback (likely just a brand name)
      if (!fallback) fallback = candidate;
    }
    return cleanTitle(fallback);
  }

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const title = extractTitle(el);

    // Price — use innerText and regex (handles .a-price-whole + .a-price-fraction)
    const priceContainer = el.querySelector('.a-price:not([data-a-strike]) .a-offscreen')
      || el.querySelector('.a-price:not([data-a-strike])');
    let price = 0;
    if (priceContainer) {
      const priceMatch = priceContainer.innerText.match(/\$[\d,]+\.?\d*/);
      if (priceMatch) price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
    }
    // Fallback: try card innerText for price
    if (price === 0) {
      const textMatch = el.innerText.match(/\$[\d,]+\.\d{2}/);
      if (textMatch) price = parseFloat(textMatch[0].replace(/[$,]/g, ''));
    }

    // Original price (strikethrough)
    let original_price = null;
    const strikePrice = el.querySelector('.a-price[data-a-strike] .a-offscreen')
      || el.querySelector('.a-text-price .a-offscreen')
      || el.querySelector('.a-price[data-a-strike]');
    if (strikePrice) {
      const origMatch = strikePrice.innerText.match(/\$[\d,]+\.?\d*/);
      if (origMatch) {
        const origVal = parseFloat(origMatch[0].replace(/[$,]/g, ''));
        if (origVal > price) original_price = origVal;
      }
    }

    // URL — product link
    const linkEl = el.querySelector('a[href*="/dp/"]') || el.querySelector('h2 a[href]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.amazon.com' + url;
    }

    // Image
    const imgEl = el.querySelector('img.s-image');
    const image_url = imgEl ? imgEl.src : null;

    // Rating
    const ratingEl = el.querySelector('.a-icon-alt');
    const ratingText = ratingEl ? ratingEl.innerText : '';
    const ratingMatch = ratingText.match(/([\d.]+)\s*out\s*of/);

    // ASIN
    const asin = el.getAttribute('data-asin');

    return {
      position: i + 1,
      title,
      price,
      original_price,
      currency: 'USD',
      url,
      condition: 'new',
      is_available: true,
      image_url,
      seller: null,
      extraction_method: 'dom_eval'
    };
  });

  // 4. Return as JSON with metadata
  return JSON.stringify({
    listings,
    metadata: {
      url: location.href,
      extracted_at: new Date().toISOString(),
      count: listings.length,
      bot_detected: false
    }
  }, null, 2);
})()
