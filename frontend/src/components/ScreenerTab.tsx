/**
 * Production Screener UI — consumes /api/screener.
 * Shows — / NOT QUALIFIED / NOT AVAILABLE for nulls; never fakes 0.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Search,
  RefreshCw,
  AlertTriangle,
  Filter,
  ChevronRight,
} from 'lucide-react';
import type { ScreenerResult, ScreenerTimeframe } from '../types';
import { fetchScreener } from '../services/api';

interface ScreenerTabProps {
  onSelectTicker?: (ticker: string) => void;
}

function dash(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number' && !Number.isFinite(value)) return fallback;
  return String(value);
}

function fmtNum(value: unknown, digits = 2): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('en-US', {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  });
}

function fmtPct(value: unknown, digits = 2): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(digits)}%`;
}

function fmtLevel(value: unknown): string {
  if (value === null || value === undefined) return 'NOT QUALIFIED';
  const n = Number(value);
  if (!Number.isFinite(n)) return 'NOT AVAILABLE';
  return fmtNum(n, 0);
}

function fmtRR(value: unknown): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `1:${n.toFixed(2)}`;
}

function fmtHistProb(row: ScreenerResult): string {
  if (row.stats_status === 'INSUFFICIENT_SAMPLE') {
    return 'Insufficient Sample';
  }
  if (row.historical_tp_probability == null) return 'NOT AVAILABLE';
  return `${Number(row.historical_tp_probability).toFixed(1)}%`;
}

const TIMEFRAMES: { id: ScreenerTimeframe; label: string; blurb: string }[] = [
  {
    id: 'close_pressure',
    label: 'Close Pressure',
    blurb: 'EOD proxy · windows 14:30–16:02 · RR≥1:2 · min +3% opportunity',
  },
  {
    id: 'swing',
    label: 'Swing',
    blurb: 'Daily structure engine (separate from intraday CP)',
  },
  {
    id: 'long_term',
    label: 'Long-Term',
    blurb: 'CANDIDATE only · fundamentals when available',
  },
];

export const ScreenerTab: React.FC<ScreenerTabProps> = ({ onSelectTicker }) => {
  const [timeframe, setTimeframe] = useState<ScreenerTimeframe>('close_pressure');
  const [ticker, setTicker] = useState('');
  const [setup, setSetup] = useState('');
  const [results, setResults] = useState<ScreenerResult[]>([]);
  const [meta, setMeta] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [includeNQ, setIncludeNQ] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchScreener({
        timeframe,
        ticker: ticker.trim() || undefined,
        setup: setup.trim() || undefined,
        limit: 40,
        include_not_qualified: includeNQ,
      });
      setResults(Array.isArray(data.results) ? data.results : []);
      setMeta(data.meta ?? null);
    } catch (e) {
      setResults([]);
      setMeta(null);
      setError(e instanceof Error ? e.message : 'Failed to load screener');
    } finally {
      setLoading(false);
    }
  }, [timeframe, ticker, setup, includeNQ]);

  useEffect(() => {
    void load();
  }, [load]);

  const blurb = TIMEFRAMES.find((t) => t.id === timeframe)?.blurb;

  return (
    <div className="tab-panel active">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: '1rem',
          flexWrap: 'wrap',
          marginBottom: '1.25rem',
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '1.35rem', color: '#f1f5f9' }}>
            Screener
          </h2>
          <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
            DATA → FEATURE → SIGNAL → TARGET → RISK → HISTORICAL STATS
          </p>
          <p style={{ margin: '0.35rem 0 0', color: '#fde68a', fontSize: '0.8rem' }}>
            production_eligibility ={' '}
            <strong>
              {dash(
                (meta?.production_eligibility as string | undefined) ?? 'NOT_VALIDATED',
              )}
            </strong>
            {' '}— decision support only; not a validated production BUY.
            Cost/slippage NOT_CONFIGURED · survivorship NOT_VALIDATED.
          </p>
          {blurb && (
            <p style={{ margin: '0.25rem 0 0', color: '#94a3b8', fontSize: '0.8rem' }}>
              {blurb}
            </p>
          )}
        </div>
        <button
          type="button"
          className="nav-btn active"
          onClick={() => void load()}
          disabled={loading}
          style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}
        >
          <RefreshCw size={14} className={loading ? 'spin' : undefined} />
          Refresh
        </button>
      </div>

      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf.id}
            type="button"
            onClick={() => setTimeframe(tf.id)}
            className={timeframe === tf.id ? 'nav-btn active' : 'nav-btn'}
            style={{ padding: '0.45rem 0.9rem', cursor: 'pointer' }}
          >
            {tf.label}
          </button>
        ))}
      </div>

      <div
        className="glass-card"
        style={{
          display: 'flex',
          gap: '0.75rem',
          flexWrap: 'wrap',
          alignItems: 'center',
          marginBottom: '1rem',
          padding: '0.85rem 1rem',
        }}
      >
        <Filter size={14} color="#94a3b8" />
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Search size={14} color="#94a3b8" />
          <input
            className="form-control"
            style={{ width: '110px', textTransform: 'uppercase' }}
            placeholder="Ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === 'Enter' && void load()}
          />
        </div>
        <input
          className="form-control"
          style={{ width: '180px' }}
          placeholder="Setup filter"
          value={setup}
          onChange={(e) => setSetup(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && void load()}
        />
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.8rem', color: '#94a3b8' }}>
          <input
            type="checkbox"
            checked={includeNQ}
            onChange={(e) => setIncludeNQ(e.target.checked)}
          />
          Include NOT QUALIFIED
        </label>
      </div>

      {meta && Array.isArray(meta.limitations) && (
        <div
          style={{
            marginBottom: '1rem',
            padding: '0.75rem 1rem',
            borderRadius: 8,
            border: '1px solid rgba(234, 179, 8, 0.35)',
            background: 'rgba(234, 179, 8, 0.06)',
            fontSize: '0.78rem',
            color: '#fde68a',
          }}
        >
          <strong style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <AlertTriangle size={14} /> Data limitations
          </strong>
          <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.1rem' }}>
            {(meta.limitations as string[]).slice(0, 4).map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <div style={{ marginTop: 6, color: '#94a3b8' }}>
            as_of {dash(meta.as_of)} · matched {dash(meta.total_matched)} · engine{' '}
            {dash(meta.engine_version)}
          </div>
        </div>
      )}

      {error && (
        <div className="error-banner" style={{ marginBottom: '1rem' }}>
          <AlertTriangle size={20} />
          <span>{error}</span>
        </div>
      )}

      {loading && results.length === 0 && (
        <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem' }}>
          Loading screener…
        </p>
      )}

      {!loading && !error && results.length === 0 && (
        <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem' }}>
          Empty screener result — no qualified setups (or data unavailable).
        </p>
      )}

      {results.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: '0.78rem',
              color: '#e2e8f0',
            }}
          >
            <thead>
              <tr style={{ textAlign: 'left', color: '#94a3b8', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                {[
                  'Ticker',
                  'Company',
                  'Price',
                  'Change',
                  'Volume',
                  'Value',
                  'Setup',
                  'Score',
                  'Trend',
                  'Pressure',
                  'Foreign',
                  'Liquidity',
                  'Entry',
                  'TP1',
                  'TP2',
                  'TP3',
                  'CL1',
                  'CL2',
                  'CL3',
                  'RR1',
                  'RR2',
                  'RR3',
                  'TP Prob',
                  'Med Days',
                  'MFE',
                  'MAE',
                  'n',
                  'DQ',
                  'Conf',
                  'Elig',
                  'Why',
                ].map((h) => (
                  <th key={h} style={{ padding: '0.55rem 0.45rem', whiteSpace: 'nowrap', fontWeight: 600 }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {results.map((row) => (
                <tr
                  key={`${row.ticker}-${row.setup}-${row.as_of}`}
                  style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', cursor: onSelectTicker ? 'pointer' : 'default' }}
                  onClick={() => onSelectTicker?.(row.ticker)}
                >
                  <td style={{ padding: '0.5rem 0.45rem', fontWeight: 700, fontFamily: 'monospace' }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                      {row.ticker}
                      <ChevronRight size={12} color="#64748b" />
                    </span>
                  </td>
                  <td style={{ padding: '0.5rem 0.45rem', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {dash(row.company)}
                  </td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.price, 0)}</td>
                  <td
                    style={{
                      padding: '0.5rem 0.45rem',
                      fontFamily: 'monospace',
                      color:
                        row.change_pct == null
                          ? undefined
                          : Number(row.change_pct) >= 0
                            ? '#34d399'
                            : '#f87171',
                    }}
                  >
                    {fmtPct(row.change_pct)}
                  </td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.volume, 0)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.value, 0)}</td>
                  <td style={{ padding: '0.5rem 0.45rem' }}>
                    {row.setup === 'NOT_QUALIFIED' ? 'NOT QUALIFIED' : dash(row.setup)}
                  </td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.engine_score, 1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem' }}>{dash(row.trend)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.pressure, 1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.foreign, 0)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.liquidity, 0)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.entry_zone)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.tp1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.tp2)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.tp3)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.cl1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.cl2)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtLevel(row.cl3)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtRR(row.rr1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtRR(row.rr2)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtRR(row.rr3)}</td>
                  <td style={{ padding: '0.5rem 0.45rem' }}>{fmtHistProb(row)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.median_days, 1)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtPct(row.mfe)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtPct(row.mae)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>
                    {row.sample_size != null ? String(row.sample_size) : '—'}
                  </td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{dash(row.data_quality)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace' }}>{fmtNum(row.confidence, 2)}</td>
                  <td style={{ padding: '0.5rem 0.45rem', fontFamily: 'monospace', color: '#fde68a' }}>
                    {dash(row.production_eligibility ?? 'NOT_VALIDATED')}
                  </td>
                  <td
                    style={{
                      padding: '0.5rem 0.45rem',
                      maxWidth: 260,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      color: '#94a3b8',
                    }}
                    title={row.why_signal || undefined}
                  >
                    {dash(row.why_signal)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
