// Target extraction — DOM eval for search results.
// Anchor: [data-test="@web/site-top-of-funnel/ProductCardWrapper"]
// Target has clean data-test attributes on everything.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all product card wrappers
  const cards = document.querySelectorAll('[data-test="@web/site-top-of-funnel/ProductCardWrapper"]');

  // 2. Deduplicate by product URL
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const link = el.querySelector('a[href*="/p/"]');
    const key = link ? link.href.split('?')[0] : el.innerText.slice(0, 50);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const text = el.innerText.trim();

    // Title
    const titleEl = el.querySelector('[data-test="product-title"] a')
      || el.querySelector('a[data-test="product-title"]')
      || el.querySelector('[data-test="product-title"]');
    let title = titleEl ? titleEl.innerText.trim() : '';
    if (!title) {
      // Fallback: first substantial non-price text line
      const lines = text.split('\n').filter(l => l.trim().length > 5 && !/^\$/.test(l.trim()));
      title = lines[0] ? lines[0].trim().slice(0, 200) : '';
    }

    // Price — extract all dollar amounts from the card
    const priceMatches = text.match(/\$[\d,]+\.?\d*/g);
    let price = 0;
    let original_price = null;
    if (priceMatches && priceMatches.length > 0) {
      price = parseFloat(priceMatches[0].replace(/[$,]/g, ''));
      // Second price is often the original (reg.) price
      if (priceMatches.length > 1) {
        const second = parseFloat(priceMatches[1].replace(/[$,]/g, ''));
        if (second > price) original_price = second;
      }
    }

    // Sale detection
    const saleEl = el.querySelector('[data-test="product-sale-badge"]')
      || el.querySelector('[class*="sale"]');
    const isOnSale = !!saleEl || (original_price !== null && original_price > price);

    // Rating
    const ratingEl = el.querySelector('[data-test="ratings"]');
    const ratingText = ratingEl ? ratingEl.innerText.trim() : '';

    // URL
    const linkEl = el.querySelector('a[href*="/p/"]') || el.querySelector('a[href]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.target.com' + url;
    }

    // Image
    const imgEl = el.querySelector('picture img')
      || el.querySelector('img[src*="target.scene7"]')
      || el.querySelector('img[src]');
    const image_url = imgEl ? imgEl.src : null;

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
