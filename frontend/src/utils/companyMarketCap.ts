/**
 * Normalize screener company price/valuation fields to the producer contract.
 * Does not recalculate prices, PER, PBV, or market cap.
 *
 * Canonical (producer):
 *   close, price_date, per, price_bv, estimated_mcap
 * Legacy aliases (optional consumers):
 *   price ← close, pbv ← price_bv, market_cap ← estimated_mcap
 */

export function normalizeNullableNumber(raw: unknown): number | null {
  if (raw == null || raw === '') return null;
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return null;
  return n;
}

/** Preserve producer market/data date string; never invent browser/current time. */
export function normalizePriceDate(raw: unknown): string | null {
  if (raw == null) return null;
  if (typeof raw !== 'string' && typeof raw !== 'number') return null;
  const text = String(raw).trim();
  if (!text || text === 'N/A' || text.toLowerCase() === 'null') return null;
  return text;
}

export function normalizeEstimatedMcap(raw: unknown): number | null {
  return normalizeNullableNumber(raw);
}

export type CanonicalCompanyFields = {
  close: number | null;
  price_date: string | null;
  per: number | null;
  price_bv: number | null;
  estimated_mcap: number | null;
  /** Legacy alias of `close`. */
  price: number | null;
  /** Legacy alias of `price_bv`. */
  pbv: number | null;
  /** Legacy alias of `estimated_mcap`. */
  market_cap: number | null;
};

/**
 * Map a company-like payload onto the canonical screener field contract.
 */
export function normalizeCompanyContract<T extends Record<string, unknown>>(
  company: T,
): T & CanonicalCompanyFields {
  const close = normalizeNullableNumber(
    company.close !== undefined && company.close !== null ? company.close : company.price,
  );
  const price_bv = normalizeNullableNumber(
    company.price_bv !== undefined && company.price_bv !== null
      ? company.price_bv
      : company.pbv,
  );
  const estimated_mcap = normalizeEstimatedMcap(
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
    // Legacy aliases for lingering consumers (watchlist storage key, older UI).
    price: close,
    pbv: price_bv,
    market_cap: estimated_mcap,
  };
}

/** @deprecated Prefer normalizeCompanyContract — kept for estimated_mcap-only call sites. */
export function withCanonicalEstimatedMcap<T extends Record<string, unknown>>(
  company: T,
): T & CanonicalCompanyFields {
  return normalizeCompanyContract(company);
}
