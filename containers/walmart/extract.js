// Walmart extraction — DOM eval for search results.
// Anchor: [data-item-id] — data attribute on every product card.
// Price gotcha: Prices rendered as 3 separate spans — use innerText + regex.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all product cards via data-item-id
  const cards = document.querySelectorAll('[data-item-id]');

  // 2. Deduplicate by item ID
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const itemId = el.getAttribute('data-item-id');
    if (!itemId || seen.has(itemId)) return false;
    seen.add(itemId);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const text = el.innerText.trim();

    // Title — look for product title element
    const titleEl = el.querySelector('[data-automation-id="product-title"]')
      || el.querySelector('span[data-automation-id="product-title"]')
      || el.querySelector('[class*="product-title"]');
    let title = '';
    if (titleEl) {
      title = titleEl.innerText.trim();
    } else {
      // Fallback: first substantial text line (skip price lines)
      const lines = text.split('\n').filter(l => l.trim().length > 10 && !/^\$/.test(l.trim()));
      title = lines[0] ? lines[0].trim().slice(0, 200) : '';
    }

    // Price — use innerText to handle 3-span layout: <span>$</span><span>269</span><span>98</span>
    // The innerText concatenates them, so regex picks up the full price
    const priceMatches = text.match(/\$[\d,]+\.?\d*/g);
    let price = 0;
    let original_price = null;
    if (priceMatches && priceMatches.length > 0) {
      price = parseFloat(priceMatches[0].replace(/[$,]/g, ''));
      // If there's a second price and it's higher, it's the original
      if (priceMatches.length > 1) {
        const second = parseFloat(priceMatches[1].replace(/[$,]/g, ''));
        if (second > price) original_price = second;
      }
    }

    // URL
    const linkEl = el.querySelector('a[href*="/ip/"]') || el.querySelector('a[href]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.walmart.com' + url;
    }

    // Image
    const imgEl = el.querySelector('img[data-testid="productTileImage"]')
      || el.querySelector('img[src*="walmartimages"]')
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
