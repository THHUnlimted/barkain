// Sam's Club extraction — DOM eval for search results.
// Anchor selector: best-guess — tries multiple patterns since not fully tested.
// Primary: [data-testid] product cards, fallback: product link patterns.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select product cards — try multiple selector strategies
  let cards = document.querySelectorAll('[data-testid="productCard"]');
  if (cards.length === 0) {
    cards = document.querySelectorAll('[data-testid="product-card"]');
  }
  if (cards.length === 0) {
    cards = document.querySelectorAll('[data-item-id]');
  }
  if (cards.length === 0) {
    // Fallback: find product links and use their parent containers
    const links = document.querySelectorAll('a[href*="/p/"]');
    const parents = new Set();
    links.forEach(a => {
      // Walk up to find a reasonable card container
      let el = a.parentElement;
      for (let depth = 0; depth < 5 && el; depth++) {
        if (el.children.length >= 2 && el.offsetHeight > 100) {
          parents.add(el);
          break;
        }
        el = el.parentElement;
      }
    });
    cards = Array.from(parents);
  }

  // 2. Deduplicate
  const seen = new Set();
  const unique = Array.from(cards).filter(el => {
    const link = el.querySelector('a[href*="/p/"]') || el.querySelector('a[href]');
    const key = link ? link.href.split('?')[0] : el.innerText.slice(0, 50);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const text = el.innerText.trim();

    // Title
    const titleEl = el.querySelector('[class*="Title"], [class*="title"], h3, h2, [data-testid*="title"]');
    let title = titleEl ? titleEl.innerText.trim() : '';
    if (!title) {
      const lines = text.split('\n').filter(l => l.trim().length > 10 && !/^\$/.test(l.trim()));
      title = lines[0] ? lines[0].trim().slice(0, 200) : '';
    }

    // Price
    const priceMatches = text.match(/\$[\d,]+\.?\d*/g);
    let price = 0;
    let original_price = null;
    if (priceMatches && priceMatches.length > 0) {
      price = parseFloat(priceMatches[0].replace(/[$,]/g, ''));
      if (priceMatches.length > 1) {
        const second = parseFloat(priceMatches[1].replace(/[$,]/g, ''));
        if (second > price) original_price = second;
      }
    }

    // URL
    const linkEl = el.querySelector('a[href*="/p/"]') || el.querySelector('a[href]');
    let url = linkEl ? linkEl.href : '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.samsclub.com' + url;
    }

    // Image
    const imgEl = el.querySelector('img[src*="samsclub"]')
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
