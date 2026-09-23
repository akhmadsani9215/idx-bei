/**
 * Market-date helpers for Screener / Terminal as-of display.
 * Treat date-only and ISO timestamps as calendar market dates (YYYY-MM-DD),
 * never as browser "now".
 */

export type MarketDateKey = string; // YYYY-MM-DD

/** Extract a comparable YYYY-MM-DD key from producer/API date strings. */
export function parseMarketDateKey(value: unknown): MarketDateKey | null {
  if (value == null) return null;
  if (typeof value !== 'string' && typeof value !== 'number') return null;

  const text = String(value).trim();
  if (!text || text === 'N/A' || text.toLowerCase() === 'null') return null;

  // Prefer leading YYYY-MM-DD (covers "2026-09-21", "2026-09-21 00:00:00", ISO)
  const leading = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (leading) {
    const key = `${leading[1]}-${leading[2]}-${leading[3]}`;
    return isValidYmd(key) ? key : null;
  }

  // YYYYMMDD
  const compact = text.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compact) {
    const key = `${compact[1]}-${compact[2]}-${compact[3]}`;
    return isValidYmd(key) ? key : null;
  }

  return null;
}

function isValidYmd(key: string): boolean {
  const m = key.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return false;
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  // Calendar check via UTC noon to avoid TZ day-shift
  const dt = new Date(Date.UTC(y, mo - 1, d, 12, 0, 0));
  return (
    dt.getUTCFullYear() === y &&
    dt.getUTCMonth() === mo - 1 &&
    dt.getUTCDate() === d
  );
}

/** Human-readable label for UI (data date, not a live clock). */
export function formatMarketDateLabel(value: unknown): string | null {
  const key = parseMarketDateKey(value);
  return key;
}

/**
 * True only when both dates parse and screener is strictly older than terminal.
 * Equal dates or missing/invalid → false (no warning).
 */
export function isScreenerOlderThanTerminal(
  screenerDate: unknown,
  terminalDate: unknown,
): boolean {
  const s = parseMarketDateKey(screenerDate);
  const t = parseMarketDateKey(terminalDate);
  if (!s || !t) return false;
  return s < t;
}

/** Prefer company price_date; fall back to snapshot last_updated for lag checks. */
export function resolveScreenerAsOf(
  priceDate: unknown,
  snapshotLastUpdated: unknown,
): MarketDateKey | null {
  return parseMarketDateKey(priceDate) ?? parseMarketDateKey(snapshotLastUpdated);
}
