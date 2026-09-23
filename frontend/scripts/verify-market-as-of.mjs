/**
 * Lightweight self-check for market as-of + price/valuation field contract.
 * Mirrors frontend/src/utils/marketAsOf.ts and companyMarketCap.ts — keep in sync.
 * Run: node frontend/scripts/verify-market-as-of.mjs
 */

function parseMarketDateKey(value) {
  if (value == null) return null;
  if (typeof value !== 'string' && typeof value !== 'number') return null;
  const text = String(value).trim();
  if (!text || text === 'N/A' || text.toLowerCase() === 'null') return null;
  const leading = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (leading) {
    const key = `${leading[1]}-${leading[2]}-${leading[3]}`;
    return isValidYmd(key) ? key : null;
  }
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compact) {
    const key = `${compact[1]}-${compact[2]}-${compact[3]}`;
    return isValidYmd(key) ? key : null;
  }
  return null;
}

function isValidYmd(key) {
  const m = key.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return false;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  const dt = new Date(Date.UTC(y, mo - 1, d, 12, 0, 0));
  return dt.getUTCFullYear() === y && dt.getUTCMonth() === mo - 1 && dt.getUTCDate() === d;
}

function isScreenerOlderThanTerminal(screenerDate, terminalDate) {
  const s = parseMarketDateKey(screenerDate);
  const t = parseMarketDateKey(terminalDate);
  if (!s || !t) return false;
  return s < t;
}

function resolveScreenerAsOf(priceDate, snapshotLastUpdated) {
  return parseMarketDateKey(priceDate) ?? parseMarketDateKey(snapshotLastUpdated);
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function normalizeNullableNumber(raw) {
  if (raw == null || raw === '') return null;
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return null;
  return n;
}

function normalizePriceDate(raw) {
  if (raw == null) return null;
  if (typeof raw !== 'string' && typeof raw !== 'number') return null;
  const text = String(raw).trim();
  if (!text || text === 'N/A' || text.toLowerCase() === 'null') return null;
  return text;
}

function normalizeCompanyContract(company) {
  const close = normalizeNullableNumber(
    company.close !== undefined && company.close !== null ? company.close : company.price,
  );
  const price_bv = normalizeNullableNumber(
    company.price_bv !== undefined && company.price_bv !== null
      ? company.price_bv
      : company.pbv,
  );
  const estimated_mcap = normalizeNullableNumber(
    company.estimated_mcap !== undefined && company.estimated_mcap !== null
      ? company.estimated_mcap
      : company.market_cap,
  );
  const per = normalizeNullableNumber(company.per);
  const price_date = normalizePriceDate(company.price_date);
  return {
    ...company,
    close,
    price_date,
    per,
    price_bv,
    estimated_mcap,
    price: close,
    pbv: price_bv,
    market_cap: estimated_mcap,
  };
}

// --- as-of checks ---
assert(parseMarketDateKey('2026-09-21 19:57:32') === '2026-09-21', 'parse last_updated');
assert(parseMarketDateKey('2026-09-22') === '2026-09-22', 'parse date-only');
assert(parseMarketDateKey('2026-09-22T00:00:00') === '2026-09-22', 'parse ISO');
assert(parseMarketDateKey(null) === null, 'null');
assert(parseMarketDateKey('N/A') === null, 'N/A');
assert(parseMarketDateKey('bogus') === null, 'invalid');

const fetched = {
  companies: [{ code: 'BBCA', price_date: '2026-09-21 00:00:00' }],
  last_updated: '2026-09-21 19:57:32',
};
assert(parseMarketDateKey(fetched.last_updated) === '2026-09-21', 'DashboardData.last_updated survives');
assert(isScreenerOlderThanTerminal('2026-09-21', '2026-09-22') === true, 'screener older');
assert(isScreenerOlderThanTerminal('2026-09-22', '2026-09-22') === false, 'same date');
assert(isScreenerOlderThanTerminal(null, '2026-09-22') === false, 'missing screener');
assert(resolveScreenerAsOf('2026-09-21 00:00:00', '2026-09-20 19:00:00') === '2026-09-21', 'prefer price_date');

// --- price / valuation contract ---
const fromProducer = normalizeCompanyContract({
  code: 'ADRO',
  close: 2620,
  price: 1,
  price_bv: 0.65,
  pbv: 9,
  per: 3.3,
  price_date: '2026-09-21 00:00:00',
  estimated_mcap: 75457.29,
  market_cap: 1,
});
assert(fromProducer.close === 2620, 'canonical close from producer');
assert(fromProducer.price === 2620, 'legacy price alias mirrors close');
assert(fromProducer.price_bv === 0.65, 'canonical price_bv');
assert(fromProducer.pbv === 0.65, 'legacy pbv mirrors price_bv');
assert(fromProducer.per === 3.3, 'per');
assert(fromProducer.price_date === '2026-09-21 00:00:00', 'price_date preserved');
assert(fromProducer.estimated_mcap === 75457.29, 'estimated_mcap not overridden');
assert(fromProducer.market_cap === 75457.29, 'legacy market_cap mirrors estimated_mcap');

const fromLegacy = normalizeCompanyContract({
  code: 'BBCA',
  price: 9000,
  pbv: 2.1,
  market_cap: 500,
});
assert(fromLegacy.close === 9000, 'legacy price → close');
assert(fromLegacy.price_bv === 2.1, 'legacy pbv → price_bv');
assert(fromLegacy.estimated_mcap === 500, 'legacy market_cap → estimated_mcap');

const missing = normalizeCompanyContract({ code: 'XXXX', price_date: 'N/A' });
assert(missing.close === null, 'missing close → null');
assert(missing.price_bv === null, 'missing price_bv → null');
assert(missing.per === null, 'missing per → null');
assert(missing.estimated_mcap === null, 'missing mcap → null');
assert(missing.price_date === null, 'N/A price_date → null');

// Integrity: ranking uses numeric score desc; invalid price excluded
const ranked = [
  { code: 'A', score: { total: 50 }, close: 100 },
  { code: 'B', score: { total: 90 }, close: 200 },
  { code: 'C', score: { total: 70 }, close: null },
]
  .filter((c) => c.close != null && Number(c.close) > 0)
  .sort((a, b) => (b.score?.total ?? -Infinity) - (a.score?.total ?? -Infinity));
assert(ranked.map((c) => c.code).join(',') === 'B,A', 'score desc + drop null close');

// trade_date must not invent browser clock — only from snapshot meta / price_date
assert(parseMarketDateKey(new Date().toISOString()) != null, 'iso parses but must not be used as fabricated trade_date source in UI');
assert(parseMarketDateKey(null) === null, 'null trade_date stays null');

console.log('verify-market-as-of: PASS');
