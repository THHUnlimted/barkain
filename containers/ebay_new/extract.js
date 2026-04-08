// eBay (New) extraction — DOM eval for search results filtered to new condition.
// Anchor: .s-item — eBay's stable search result class.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all search result items (skip the first .s-item which is often a header)
  const allItems = document.querySelectorAll('.s-item');
  const cards = Array.from(allItems).filter(el => {
    const link = el.querySelector('.s-item__link');
    return link && link.href && link.href.includes('/itm/');
  });

  // 2. Deduplicate by item URL
  const seen = new Set();
  const unique = cards.filter(el => {
    const link = el.querySelector('.s-item__link');
    const key = link ? link.href.split('?')[0] : '';
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  // 3. Extract fields from each listing
  const listings = unique.slice(0, MAX).map((el, i) => {
    // Title
    const titleEl = el.querySelector('.s-item__title span[role="heading"]')
      || el.querySelector('.s-item__title span')
      || el.querySelector('.s-item__title');
    let title = titleEl ? titleEl.innerText.trim() : '';
    // Clean "New Listing" prefix
    title = title.replace(/^New Listing\s*/i, '');

    // Price
    const priceEl = el.querySelector('.s-item__price');
    let price = 0;
    if (priceEl) {
      const priceMatch = priceEl.innerText.match(/\$[\d,]+\.?\d*/);
      if (priceMatch) price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
    }

    // Original price (was price / strikethrough)
    let original_price = null;
    const origEl = el.querySelector('.s-item__detail--delete .STRIKETHROUGH')
      || el.querySelector('.s-item__etrs-text');
    if (origEl) {
      const origMatch = origEl.innerText.match(/\$[\d,]+\.?\d*/);
      if (origMatch) {
        const origVal = parseFloat(origMatch[0].replace(/[$,]/g, ''));
        if (origVal > price) original_price = origVal;
      }
    }

    // URL
    const linkEl = el.querySelector('.s-item__link');
    const url = linkEl ? linkEl.href : '';

    // Image
    const imgEl = el.querySelector('.s-item__image-wrapper img');
    const image_url = imgEl ? (imgEl.src || imgEl.getAttribute('data-src')) : null;

    // Seller
    const sellerEl = el.querySelector('.s-item__seller-info-text')
      || el.querySelector('.s-item__seller-info');
    const seller = sellerEl ? sellerEl.innerText.trim() : null;

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
      seller,
      extraction_method: 'dom_eval'
    };
  });

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
