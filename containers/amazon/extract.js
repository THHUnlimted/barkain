// Amazon extraction — DOM eval for search results.
// Anchor: [data-component-type="s-search-result"] with data-asin attribute.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
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

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    // Title — fallback chain: [data-cy="title-recipe"] span → h2 a span → img alt
    let title = '';
    const titleRecipe = el.querySelector('[data-cy="title-recipe"] span');
    if (titleRecipe) {
      title = titleRecipe.innerText.trim();
    }
    if (!title) {
      const h2Span = el.querySelector('h2 a span');
      if (h2Span) title = h2Span.innerText.trim();
    }
    if (!title) {
      const imgAlt = el.querySelector('img[alt]');
      if (imgAlt) title = imgAlt.alt.trim();
    }
    title = cleanTitle(title);

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
