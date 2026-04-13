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

  // Sponsored noise patterns to strip from titles.
  // Amazon uses curly apostrophes (U+2019), so each apostrophe slot matches ['\u2019].
  const SPONSORED_NOISE = [
    /Sponsored\s*/gi,
    /You['\u2019]re seeing this ad based on the product['\u2019]s relevance to your search query\.?\s*/gi,
    /Leave ad feedback\s*/gi,
    /You['\u2019]re seeing this ad\s*/gi
  ];

  function cleanTitle(text) {
    let cleaned = text;
    for (const pattern of SPONSORED_NOISE) {
      cleaned = cleaned.replace(pattern, '');
    }
    return cleaned.trim();
  }

  // Title extraction — Amazon often splits the brand and product name into sibling
  // <span> elements inside h2/title-recipe (e.g. <span>Sony</span><span>WH-1000XM5 ...</span>).
  // Grabbing a single span returns only the brand. Join all span innerText values,
  // then fall back to full-container innerText, then image alt.
  function isSubstantive(s) {
    if (!s || s.length < 3) return false;
    const wc = s.split(/\s+/).length;
    return wc >= 3 || s.length > 20;
  }

  function joinSpans(container) {
    if (!container) return '';
    const spans = container.querySelectorAll('span');
    if (!spans.length) return '';
    const seen = new Set();
    const parts = [];
    for (const s of spans) {
      const t = (s.innerText || '').trim();
      if (!t) continue;
      // Skip spans that are strict prefixes of existing parts (nested duplicates)
      if (seen.has(t)) continue;
      seen.add(t);
      parts.push(t);
    }
    return parts.join(' ').trim();
  }

  function extractTitle(el) {
    const candidates = [];

    // Strategy 1: join spans inside [data-cy="title-recipe"] (handles split brand/product)
    const titleRecipe = el.querySelector('[data-cy="title-recipe"]');
    if (titleRecipe) {
      candidates.push(joinSpans(titleRecipe));
      candidates.push((titleRecipe.innerText || '').trim());
    }

    // Strategy 2: join spans inside h2 (same pattern, different anchor)
    const h2 = el.querySelector('h2');
    if (h2) {
      candidates.push(joinSpans(h2));
      candidates.push((h2.innerText || '').trim());
    }

    // Strategy 3: h2 a innerText directly
    const h2a = el.querySelector('h2 a');
    if (h2a) candidates.push((h2a.innerText || '').trim());

    // Strategy 4: image alt fallback
    const img = el.querySelector('img.s-image')
      || el.querySelector('img[data-image-latency="s-product-image"]');
    if (img && img.alt) candidates.push(img.alt.trim());

    // Return the first substantive candidate
    let fallback = '';
    for (const raw of candidates) {
      if (!raw) continue;
      const cleaned = cleanTitle(raw);
      if (isSubstantive(cleaned)) return cleaned;
      if (!fallback && cleaned.length >= 3) fallback = cleaned;
    }
    return fallback;
  }

  // Detect condition from a listing title. Amazon marks refurb products with
  // phrases like "Renewed", "Refurbished", "Certified Pre-Owned" in the title.
  function detectCondition(title) {
    if (!title) return 'new';
    const lower = title.toLowerCase();
    if (/\brenewed\b|\brefurbished\b|\brecertified\b|\bre-certified\b|\bcertified\s+pre-?owned\b|\bpre-?owned\b/.test(lower)) {
      return 'refurbished';
    }
    if (/\bused\b|\bopen\s*box\b/.test(lower)) {
      return 'used';
    }
    return 'new';
  }

  // Extract the full product price, skipping installment / monthly offers.
  // Amazon sometimes shows "$45.00/mo" for phones on payment plans — those are
  // rendered as a regular .a-price element but with "/mo" text in the parent row.
  // Detect that and reject, falling back to the outright (full) price.
  function extractPrice(el) {
    const INSTALLMENT_RE = /\$[\d,]+(?:\.\d{1,2})?\s*\/\s*mo\b|\/\s*month\b|\bper\s*month\b|\bmonthly\s+payment\b|\bfrom\s*\$[\d,]+\s*\/\s*mo\b/i;
    const priceEls = Array.from(el.querySelectorAll('.a-price:not([data-a-strike])'));
    const candidates = [];

    for (const priceEl of priceEls) {
      // Walk up a few levels to find the containing row — installment offers
      // often show "/mo" as a sibling of the price, not a child.
      const context = (priceEl.closest('.a-row, .a-section')?.innerText
        || priceEl.parentElement?.innerText
        || priceEl.innerText
        || '');
      if (INSTALLMENT_RE.test(context)) continue;

      const offscreen = priceEl.querySelector('.a-offscreen');
      const text = (offscreen?.innerText || priceEl.innerText || '');
      const match = text.match(/\$[\d,]+\.?\d*/);
      if (match) {
        const val = parseFloat(match[0].replace(/[$,]/g, ''));
        if (val > 0) candidates.push(val);
      }
    }

    if (candidates.length > 0) {
      // Full prices are almost always larger than any per-item fragment (e.g. shipping)
      // but smaller than strikethroughs (which we already excluded via :not).
      return Math.max(...candidates);
    }

    // Fallback: scan the whole card innerText for any dollar amount, reject /mo context
    const rawText = el.innerText || '';
    if (INSTALLMENT_RE.test(rawText)) {
      // Card shows installment offer — try to find a non-installment price by
      // stripping the "/mo" fragment first
      const stripped = rawText.replace(INSTALLMENT_RE, ' ');
      const textMatch = stripped.match(/\$[\d,]+\.\d{2}/);
      if (textMatch) return parseFloat(textMatch[0].replace(/[$,]/g, ''));
      return 0;
    }
    const textMatch = rawText.match(/\$[\d,]+\.\d{2}/);
    if (textMatch) return parseFloat(textMatch[0].replace(/[$,]/g, ''));
    return 0;
  }

  // 3. Extract fields from each card
  const listings = unique.slice(0, MAX).map((el, i) => {
    const title = extractTitle(el);
    const condition = detectCondition(title);
    const price = extractPrice(el);

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
      condition,
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
