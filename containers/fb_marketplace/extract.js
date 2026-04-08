// Facebook Marketplace extraction — DOM eval for search results.
// Anchor: a[href*="/marketplace/item/"] — URL pattern is the only stable selector.
// Class names are obfuscated and change regularly.
// All items default to condition "used" (marketplace assumption).
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all marketplace item links
  const links = document.querySelectorAll('a[href*="/marketplace/item/"]');

  // 2. Deduplicate by item ID extracted from URL
  const seen = new Set();
  const unique = Array.from(links).filter(el => {
    const match = el.href.match(/\/marketplace\/item\/(\d+)/);
    const itemId = match ? match[1] : el.href;
    if (seen.has(itemId)) return false;
    seen.add(itemId);
    return true;
  });

  // 3. Extract fields from each listing card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const text = el.innerText.trim();
    const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);

    // Price — find the line with a dollar amount
    let price = 0;
    for (const line of lines) {
      const priceMatch = line.match(/\$[\d,]+\.?\d*/);
      if (priceMatch) {
        price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
        break;
      }
    }

    // Title — first substantial line that isn't a price or "Free"
    let title = '';
    for (const line of lines) {
      if (line.length > 3 && !/^\$/.test(line) && line.toLowerCase() !== 'free') {
        title = line.slice(0, 200);
        break;
      }
    }

    // Seller / Location — typically the last lines in the card text
    let seller = null;
    if (lines.length >= 3) {
      // Last line is often the location, second-to-last might be seller
      const lastLine = lines[lines.length - 1];
      if (lastLine && !lastLine.startsWith('$') && lastLine.length > 2) {
        seller = lastLine;
      }
    }

    // URL
    let url = el.href || '';
    if (url && !url.startsWith('http')) {
      url = 'https://www.facebook.com' + url;
    }

    // Image — look within the anchor's children
    const imgEl = el.querySelector('img[src]');
    const image_url = imgEl ? imgEl.src : null;

    // Item ID from URL
    const idMatch = el.href.match(/\/marketplace\/item\/(\d+)/);

    return {
      position: i + 1,
      title,
      price,
      original_price: null,
      currency: 'USD',
      url,
      condition: 'used',
      is_available: true,
      image_url,
      seller,
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
