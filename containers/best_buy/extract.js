// Best Buy extraction — DOM eval for search results.
// Anchor: .sku-item or [data-sku-id] — Best Buy uses class-based product cards.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all product cards — try multiple selectors for resilience
  let cards = document.querySelectorAll('.sku-item');
  if (cards.length === 0) cards = document.querySelectorAll('li.sku-item');
  if (cards.length === 0) cards = document.querySelectorAll('[data-sku-id]');
  if (cards.length === 0) cards = document.querySelectorAll('[class*="sku-item"]');

  // 2. Deduplicate by data-sku-id or URL
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const skuId = el.getAttribute('data-sku-id');
    const linkEl = el.querySelector('.sku-title a, h4.sku-title a');
    const href = linkEl ? linkEl.href : '';
    const key = skuId || href;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    // Title — fallback chain: .sku-title a → h4.sku-title a → first anchor text
    let title = '';
    const titleEl = el.querySelector('.sku-title a') || el.querySelector('h4.sku-title a');
    if (titleEl) {
      title = titleEl.innerText.trim();
    }
    if (!title) {
      const anyLink = el.querySelector('a[href*="/site/"]');
      if (anyLink) title = anyLink.innerText.trim();
    }

    // Price — customer price span or regex fallback
    let price = 0;
    const priceEl = el.querySelector('.priceView-customer-price span')
      || el.querySelector('[data-testid="customer-price"] span');
    if (priceEl) {
      const priceMatch = priceEl.innerText.match(/\$[\d,]+\.?\d*/);
      if (priceMatch) price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
    }
    // Fallback: try card innerText for price
    if (price === 0) {
      const textMatch = el.innerText.match(/\$[\d,]+\.\d{2}/);
      if (textMatch) price = parseFloat(textMatch[0].replace(/[$,]/g, ''));
    }

    // Original price (regular/strikethrough price)
    let original_price = null;
    const origPriceEl = el.querySelector('.pricing-price__regular-price')
      || el.querySelector('.pricing-price__was-price')
      || el.querySelector('[data-testid="regular-price"]');
    if (origPriceEl) {
      const origMatch = origPriceEl.innerText.match(/\$[\d,]+\.?\d*/);
      if (origMatch) {
        const origVal = parseFloat(origMatch[0].replace(/[$,]/g, ''));
        if (origVal > price) original_price = origVal;
      }
    }

    // URL — product link
    const linkEl = el.querySelector('.sku-title a') || el.querySelector('h4.sku-title a')
      || el.querySelector('a[href*="/site/"]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.bestbuy.com' + url;
    }

    // Image
    const imgEl = el.querySelector('.product-image img') || el.querySelector('img[src*="bestbuy"]')
      || el.querySelector('img');
    const image_url = imgEl ? imgEl.src : null;

    // Rating
    const ratingEl = el.querySelector('.c-ratings-reviews');
    const ratingText = ratingEl ? ratingEl.innerText : '';
    const ratingMatch = ratingText.match(/([\d.]+)/);

    // SKU ID
    const skuId = el.getAttribute('data-sku-id') || '';

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
