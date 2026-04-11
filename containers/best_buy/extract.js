// Best Buy extraction — DOM eval for search results.
// Updated 2026-04-10 after live validation on EC2 — Best Buy migrated from `.sku-item`
// to React/Tailwind stack. `a.sku-title` link class survived the migration.
// Card anchor: walk up from `a.sku-title` to `.list-item` container.
// Run via: agent-browser --cdp 9222 eval --stdin < extract.js
//
// Placeholder replaced by extract.sh before execution:
//   __MAX_LISTINGS__ — maximum listings to extract

(() => {
  const MAX = __MAX_LISTINGS__;

  // 1. Select all product title links — a.sku-title is the stable anchor
  //    (also tolerates future className changes by matching startsWith)
  let titleLinks = document.querySelectorAll('a.sku-title');
  if (titleLinks.length === 0) {
    titleLinks = document.querySelectorAll('a[class^="sku-title"]');
  }
  if (titleLinks.length === 0) {
    // Fallback: any anchor that points to a /product/ page
    titleLinks = document.querySelectorAll('a[href*="/product/"]');
  }

  // 2. For each title link, walk up to find the containing card
  //    Card wrapper is usually a `.list-item` at depth ~2
  const cards = [];
  const seenUrls = new Set();
  for (const link of titleLinks) {
    // Skip empty title links (icons, etc)
    const text = (link.innerText || '').trim();
    if (!text || text.length < 5) continue;

    const href = link.href || '';
    if (!href || !href.includes('/product/')) continue;

    // Deduplicate by href (strip query + hash)
    const cleanHref = href.split('?')[0].split('#')[0];
    if (seenUrls.has(cleanHref)) continue;
    seenUrls.add(cleanHref);

    // Walk up to find the card container (list-item, sku-item, or first ancestor with a price)
    let card = link;
    for (let i = 0; i < 8 && card.parentElement; i++) {
      card = card.parentElement;
      const cls = typeof card.className === 'string' ? card.className : '';
      if (/\blist-item\b|\bsku-item\b|\bproduct-list-item\b/.test(cls)) break;
      // Fallback: stop at first ancestor containing a price
      if (i >= 2 && /\$[\d,]+\.\d{2}/.test(card.innerText)) break;
    }

    cards.push({ link, card, text, href });
    if (cards.length >= MAX) break;
  }

  // 3. Extract fields from each card
  const listings = cards.map(({ link, card, text, href }, i) => {
    // Title — use the link text (already cleaned)
    const title = text;

    // Price — find the first currency amount in the card
    let price = 0;
    let original_price = null;
    const cardText = card.innerText || '';

    // Current price: first $XXX.XX pattern
    const priceMatch = cardText.match(/\$[\d,]+\.\d{2}/);
    if (priceMatch) {
      price = parseFloat(priceMatch[0].replace(/[$,]/g, ''));
    }

    // Original price: look for "price was" / "comparable value" phrases
    const origMatch = cardText.match(/(?:price was|comp(?:arable)?\.? value(?:\s*is)?)\s*\$([\d,]+\.\d{2})/i);
    if (origMatch) {
      const origVal = parseFloat(origMatch[1].replace(/,/g, ''));
      if (origVal > price) original_price = origVal;
    }
    // Alternative: if two distinct prices appear and one is higher, treat higher as original
    if (!original_price) {
      const allPrices = Array.from(cardText.matchAll(/\$[\d,]+\.\d{2}/g))
        .map(m => parseFloat(m[0].replace(/[$,]/g, '')))
        .filter(v => v > 0);
      const unique = [...new Set(allPrices)];
      if (unique.length >= 2) {
        const maxP = Math.max(...unique);
        if (maxP > price) original_price = maxP;
      }
    }

    // URL — strip fragment/query noise but keep SKU path
    let url = href.split('#')[0];
    if (url && !url.startsWith('http')) {
      url = 'https://www.bestbuy.com' + url;
    }

    // Image — find img inside card
    const imgEl = card.querySelector('img');
    const image_url = imgEl ? (imgEl.src || imgEl.getAttribute('data-src') || null) : null;

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
