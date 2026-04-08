// Home Depot extraction — DOM eval for search results.
// Anchor: [data-testid="product-pod"] or .browse-search__pod — try data-testid attributes first.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all product cards — try multiple selectors for resilience
  let cards = document.querySelectorAll('[data-testid="product-pod"]');
  if (cards.length === 0) cards = document.querySelectorAll('.browse-search__pod');
  if (cards.length === 0) cards = document.querySelectorAll('[data-component="product"]');
  if (cards.length === 0) cards = document.querySelectorAll('.product-pod');
  if (cards.length === 0) cards = document.querySelectorAll('[data-testid="product-card"]');

  // 2. Deduplicate by product URL or data-itemid
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const itemId = el.getAttribute('data-itemid') || el.getAttribute('data-product-id');
    const linkEl = el.querySelector('a[href*="/p/"]');
    const href = linkEl ? linkEl.href : '';
    const key = itemId || href;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    // Title — fallback chain: .product-header__title → [data-testid="product-header"] a → first product link text
    let title = '';
    const titleEl = el.querySelector('.product-header__title')
      || el.querySelector('[data-testid="product-header"] a')
      || el.querySelector('[data-testid="product-title"]');
    if (titleEl) {
      title = titleEl.innerText.trim();
    }
    if (!title) {
      const anyLink = el.querySelector('a[href*="/p/"]');
      if (anyLink) title = anyLink.innerText.trim();
    }

    // Price — extract from price container using regex
    let price = 0;
    const priceContainer = el.querySelector('[data-testid="product-price"]')
      || el.querySelector('.price-format__main-price')
      || el.querySelector('[class*="price"]');
    if (priceContainer) {
      const priceMatch = priceContainer.innerText.match(/\$[\d,]+\.?\d*/);
      if (priceMatch) price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
    }
    // Fallback: try card innerText for price
    if (price === 0) {
      const textMatch = el.innerText.match(/\$[\d,]+\.\d{2}/);
      if (textMatch) price = parseFloat(textMatch[0].replace(/[$,]/g, ''));
    }

    // Original price (was price / strikethrough)
    let original_price = null;
    const origPriceEl = el.querySelector('[data-testid="was-price"]')
      || el.querySelector('.price-format__was-price')
      || el.querySelector('[class*="was-price"]');
    if (origPriceEl) {
      const origMatch = origPriceEl.innerText.match(/\$[\d,]+\.?\d*/);
      if (origMatch) {
        const origVal = parseFloat(origMatch[0].replace(/[$,]/g, ''));
        if (origVal > price) original_price = origVal;
      }
    }

    // URL — product link (Home Depot uses /p/ pattern)
    const linkEl = el.querySelector('a[href*="/p/"]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.homedepot.com' + url;
    }

    // Image
    const imgEl = el.querySelector('.stretchy img') || el.querySelector('img[src*="homedepot"]')
      || el.querySelector('img');
    const image_url = imgEl ? imgEl.src : null;

    // Rating
    const ratingEl = el.querySelector('[data-testid="product-rating"]')
      || el.querySelector('[class*="ratings"]');
    const ratingText = ratingEl ? ratingEl.innerText : '';
    const ratingMatch = ratingText.match(/([\d.]+)/);

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
