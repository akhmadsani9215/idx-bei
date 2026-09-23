import type { BacktestParams, BacktestResponse, Company, DashboardData } from '../types';
import { normalizeCompanyContract } from '../utils/companyMarketCap';

function normalizeDashboardCompanies(companies: unknown[]): Company[] {
  return companies.map((c) => {
    if (!c || typeof c !== 'object') {
      return normalizeCompanyContract({}) as unknown as Company;
    }
    return normalizeCompanyContract(c as Record<string, unknown>) as unknown as Company;
  });
}

export async function fetchDashboardData(): Promise<DashboardData> {
  // Check if loaded via window script tag fallback (supports uppercase and camelCase)
  if (typeof window !== 'undefined') {
    const globalData = (window as any).NETWORK_ALPHA_DATA || (window as any).networkAlphaData;
    if (globalData && Array.isArray(globalData.companies) && globalData.companies.length > 0) {
      return {
        companies: normalizeDashboardCompanies(globalData.companies),
        super_insiders: globalData.super_insiders ?? [],
        conglomerates: globalData.conglomerates ?? [],
        last_updated: globalData.last_updated ?? null,
      };
    }
  }

  const urls = [
    '/api/dashboard-data',
    '/data/network_alpha_data.json',
    '../data/network_alpha_data.json',
    'data/network_alpha_data.json',
    '/network_alpha_data.json',
    '/api/companies',
  ];

  for (const url of urls) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        const json = await resp.json();
        if (Array.isArray(json)) {
          return {
            companies: normalizeDashboardCompanies(json),
            super_insiders: [],
            conglomerates: [],
            last_updated: null,
          };
        }
        if (json && Array.isArray(json.companies)) {
          return {
            companies: normalizeDashboardCompanies(json.companies),
            super_insiders: json.super_insiders ?? [],
            conglomerates: json.conglomerates ?? [],
            last_updated: json.last_updated ?? null,
          };
        }
      }
    } catch {
      // try next path
    }
  }

  // Empty state when completely unreachable
  return {
    companies: [],
    super_insiders: [],
    conglomerates: [],
    last_updated: null,
  };
}

export async function fetchStockData(ticker: string): Promise<any> {
  const resp = await fetch(`/api/stock/${ticker.toUpperCase()}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch stock data for ${ticker}`);
  }
  return await resp.json();
}

export async function fetchUBO(ticker: string): Promise<any> {
  const resp = await fetch(`/api/graph/ubo/${ticker.toUpperCase()}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch UBO for ${ticker}`);
  }
  return await resp.json();
}

export async function fetchGraphNetwork(ticker: string): Promise<any> {
  const resp = await fetch(`/api/graph/network/${ticker.toUpperCase()}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch network graph for ${ticker}`);
  }
  return await resp.json();
}

export async function fetchCentrality(topN = 20): Promise<any[]> {
  const resp = await fetch(`/api/graph/centrality?top_n=${topN}`);
  if (!resp.ok) {
    throw new Error('Failed to fetch board centrality');
  }
  return await resp.json();
}

export async function fetchCrossHoldings(): Promise<any[]> {
  const resp = await fetch('/api/graph/cross-holdings');
  if (!resp.ok) {
    throw new Error('Failed to fetch cross holdings');
  }
  return await resp.json();
}

export async function fetchStealthAccumulation(lookbackDays = 5, minTurnoverRpB = 1.0): Promise<any> {
  const resp = await fetch(`/api/stealth-accumulation?lookback_days=${lookbackDays}&min_turnover_rp=${minTurnoverRpB * 1e9}`);
  if (!resp.ok) {
    throw new Error('Failed to fetch stealth accumulation');
  }
  return await resp.json();
}

export async function fetchBrokerFlow(date?: string, topK = 5): Promise<any> {
  const url = date ? `/api/broker-flow?date=${date}&top_k=${topK}` : `/api/broker-flow?top_k=${topK}`;
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error('Failed to fetch broker flow');
  }
  return await resp.json();
}

export async function fetchDividendScreen(minYield = 3.0, year = '2026', limit = 30): Promise<any> {
  const resp = await fetch(`/api/dividend?min_yield=${minYield}&year=${year}&limit=${limit}`);
  if (!resp.ok) {
    throw new Error('Failed to fetch dividend opportunities');
  }
  return await resp.json();
}

export async function fetchDividendAnalysis(ticker: string): Promise<any> {
  const resp = await fetch(`/api/dividend/${ticker.toUpperCase()}`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch dividend analysis for ${ticker}`);
  }
  return await resp.json();
}

export async function runBacktest(params: BacktestParams): Promise<BacktestResponse> {
  const resp = await fetch('/api/backtest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Backtest failed' }));
    throw new Error(err.detail || 'Backtest failed');
  }
  return await resp.json();
}

export async function fetchDailyBriefing(date?: string): Promise<any> {
  const url = date ? `/api/signals?date=${date}` : '/api/signals';
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error('Failed to fetch daily signals briefing');
  }
  return await resp.json();
}

export async function fetchStockBlocks(ticker: string): Promise<any> {
  const resp = await fetch(`/api/stock/${ticker.toUpperCase()}/blocks`);
  if (!resp.ok) {
    throw new Error(`Failed to fetch verified block trades for ${ticker}`);
  }
  return await resp.json();
}

export async function fetchIngestionStatus(): Promise<any> {
  const resp = await fetch('/api/system/ingestion-status');
  if (!resp.ok) {
    throw new Error('Failed to fetch data ingestion status');
  }
  return await resp.json();
}

export async function fetchScreener(params: {
  timeframe?: 'close_pressure' | 'swing' | 'long_term';
  ticker?: string;
  date?: string;
  setup?: string;
  signal?: string;
  limit?: number;
  cursor?: number;
  include_not_qualified?: boolean;
}): Promise<import('../types').ScreenerResponse> {
  const q = new URLSearchParams();
  if (params.timeframe) q.set('timeframe', params.timeframe);
  if (params.ticker) q.set('ticker', params.ticker);
  if (params.date) q.set('date', params.date);
  if (params.setup) q.set('setup', params.setup);
  if (params.signal) q.set('signal', params.signal);
  if (params.limit != null) q.set('limit', String(params.limit));
  if (params.cursor != null) q.set('cursor', String(params.cursor));
  if (params.include_not_qualified) q.set('include_not_qualified', 'true');
  const resp = await fetch(`/api/screener?${q.toString()}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Screener request failed' }));
    throw new Error(err.detail || 'Screener request failed');
  }
  return await resp.json();
}

export async function triggerIngestion(params: {
  job_type: 'daily' | 'backfill' | 'sync_all' | 'ownership';
  date?: string;
  start_date?: string;
  end_date?: string;
  concurrency?: number;
  path_or_url?: string;
}): Promise<any> {
  const resp = await fetch('/api/system/trigger-ingestion', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Failed to trigger ingestion' }));
    throw new Error(err.detail || 'Failed to trigger ingestion');
  }
  return await resp.json();
}

const SESSION_KEY = 'ritelinsight_session_v1';

export function getStoredSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

export function setStoredSessionId(id: string): void {
  try {
    localStorage.setItem(SESSION_KEY, id);
  } catch {
    /* ignore */
  }
}

export async function createAuthSession(label?: string): Promise<any> {
  const q = label ? `?label=${encodeURIComponent(label)}` : '';
  const resp = await fetch(`/api/auth/session${q}`, { method: 'POST' });
  if (!resp.ok) throw new Error('Failed to create session');
  return await resp.json();
}

function sessionHeaders(sessionId: string): HeadersInit {
  return { 'X-Ritel-Session': sessionId, 'Content-Type': 'application/json' };
}

export async function fetchWatchlist(sessionId: string): Promise<any> {
  const resp = await fetch('/api/watchlist', { headers: sessionHeaders(sessionId) });
  if (!resp.ok) throw new Error('Failed to fetch watchlist');
  return await resp.json();
}

export async function postWatchlistItem(sessionId: string, body: Record<string, unknown>): Promise<any> {
  const resp = await fetch('/api/watchlist', {
    method: 'POST',
    headers: sessionHeaders(sessionId),
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Add failed' }));
    throw new Error(typeof err.detail === 'string' ? err.detail : 'Add failed');
  }
  return await resp.json();
}

export async function deleteWatchlistItem(sessionId: string, ticker: string): Promise<any> {
  const resp = await fetch(`/api/watchlist/${encodeURIComponent(ticker)}`, {
    method: 'DELETE',
    headers: sessionHeaders(sessionId),
  });
  if (!resp.ok) throw new Error('Delete failed');
  return await resp.json();
}

export async function fetchStockTerminal(ticker: string, limit = 120): Promise<any> {
  const resp = await fetch(`/api/stock/${ticker.toUpperCase()}/terminal?limit=${limit}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Terminal load failed' }));
    throw new Error(err.detail || 'Terminal load failed');
  }
  return await resp.json();
}

export async function fetchBigMoney(ticker?: string): Promise<any> {
  const q = ticker ? `?ticker=${encodeURIComponent(ticker)}` : '';
  const resp = await fetch(`/api/big-money${q}`);
  if (!resp.ok) throw new Error('Big Money request failed');
  return await resp.json();
}

export async function fetchStrategyCatalog(): Promise<any> {
  const resp = await fetch('/api/strategy');
  if (!resp.ok) throw new Error('Strategy catalog failed');
  return await resp.json();
}

export async function runStrategyLab(body: Record<string, unknown>): Promise<any> {
  const resp = await fetch('/api/strategy/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: 'Strategy run failed' }));
    throw new Error(err.detail || 'Strategy run failed');
  }
  return await resp.json();
}

export async function computeTradingPlan(body: Record<string, unknown>): Promise<any> {
  const resp = await fetch('/api/trading-plan/compute', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error('Plan compute failed');
  return await resp.json();
}

export async function fetchTradingPlans(sessionId: string): Promise<any> {
  const resp = await fetch('/api/trading-plan', { headers: sessionHeaders(sessionId) });
  if (!resp.ok) throw new Error('Trading plans failed');
  return await resp.json();
}

export async function saveTradingPlan(sessionId: string, body: Record<string, unknown>): Promise<any> {
  const resp = await fetch('/api/trading-plan', {
    method: 'POST',
    headers: sessionHeaders(sessionId),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error('Save plan failed');
  return await resp.json();
}

export async function fetchJournals(sessionId: string): Promise<any> {
  const resp = await fetch('/api/journal', { headers: sessionHeaders(sessionId) });
  if (!resp.ok) throw new Error('Journal failed');
  return await resp.json();
}

export async function saveJournal(sessionId: string, body: Record<string, unknown>): Promise<any> {
  const resp = await fetch('/api/journal', {
    method: 'POST',
    headers: sessionHeaders(sessionId),
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error('Save journal failed');
  return await resp.json();
}



