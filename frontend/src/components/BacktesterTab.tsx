import React, { useEffect, useMemo, useRef, useState } from 'react';
import { PlayCircle, ShieldAlert, Loader2, BookOpen } from 'lucide-react';
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type Time,
} from 'lightweight-charts';
import type {
  BacktestParams,
  BacktestResponse,
  StrategyCatalogEntry,
  StrategyResearchResponse,
} from '../types';
import { fetchStrategyCatalog, fetchStrategyResearch, runBacktest } from '../services/api';
import { MethodologyTab } from './MethodologyTab';

interface BacktesterTabProps {
  onSelectStock: (ticker: string) => void;
}

const FALLBACK_STRATEGIES: { id: BacktestParams['strategy']; label: string }[] = [
  { id: 'foreign_flow', label: 'Foreign Flow' },
  { id: 'momentum', label: 'Momentum (Stage-1)' },
  { id: 'breakout', label: 'Breakout (Stage-1)' },
  { id: 'pullback', label: 'Pullback (Stage-1)' },
  { id: 'mean_reversion', label: 'Mean Reversion (Stage-1)' },
  { id: 'volume_expansion', label: 'Volume Expansion (Stage-1)' },
  { id: 'composite_alpha', label: 'Composite Alpha' },
  { id: 'sharia_value', label: 'Sharia Value' },
  { id: 'bandarmology', label: 'Bandarmology (volume-regime; not broker attribution)' },
  { id: 'dividend_arbitrage', label: 'Dividend Arbitrage (3-Way)' },
];

function fmtMetric(
  value: number | null | undefined,
  opts?: { suffix?: string; signed?: boolean },
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const signed = opts?.signed ? (value > 0 ? '+' : '') : '';
  return `${signed}${value}${opts?.suffix ?? ''}`;
}

function strategyLabel(id: string, catalog: StrategyCatalogEntry[]): string {
  const entry = catalog.find((s) => s.id === id);
  if (entry?.notes) return `${id} · ${entry.status}`;
  const fb = FALLBACK_STRATEGIES.find((s) => s.id === id);
  return fb?.label ?? id;
}

export const BacktesterTab: React.FC<BacktesterTabProps> = ({ onSelectStock }) => {
  const [view, setView] = useState<'lab' | 'methodology'>('lab');
  const [strategy, setStrategy] = useState<BacktestParams['strategy']>('momentum');
  const [holdingDays, setHoldingDays] = useState(7);
  const [topN, setTopN] = useState(10);
  const [stopLoss, setStopLoss] = useState(0);
  const [takeProfit, setTakeProfit] = useState(0);

  const [catalog, setCatalog] = useState<StrategyCatalogEntry[]>([]);
  const [research, setResearch] = useState<StrategyResearchResponse | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const lineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [cat, res] = await Promise.all([
          fetchStrategyCatalog().catch(() => null),
          fetchStrategyResearch().catch(() => null),
        ]);
        if (cancelled) return;
        if (cat?.strategies?.length) setCatalog(cat.strategies);
        if (res) setResearch(res);
        if (!cat && !res) setMetaError('Strategy catalog / research endpoints unavailable.');
      } catch (e) {
        if (!cancelled) setMetaError(e instanceof Error ? e.message : 'Research load failed');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedCatalog = useMemo(
    () => catalog.find((s) => s.id === strategy),
    [catalog, strategy],
  );

  const researchForStrategy = useMemo(() => {
    const engine = selectedCatalog?.engine ?? strategy;
    return (research?.trials ?? []).filter((t) => {
      return (
        t.strategy_id === strategy ||
        (engine != null && String(t.strategy_id || '').includes(String(engine)))
      );
    });
  }, [research, selectedCatalog, strategy]);

  const horizonVerdicts = selectedCatalog?.research_validation?.by_horizon ?? {};

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await runBacktest({
        strategy,
        holding_days: holdingDays,
        top_n: topN,
        min_turnover_rp: 1_000_000_000,
        stop_loss_pct: stopLoss > 0 ? stopLoss : undefined,
        take_profit_pct: takeProfit > 0 ? takeProfit : undefined,
      });
      setResult(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Backtest execution failed');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || !result || !result.equity_curve || result.equity_curve.length === 0) return;

    container.innerHTML = '';

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 360,
      layout: {
        background: { color: '#070a13' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: 'rgba(255, 255, 255, 0.1)' },
      timeScale: { borderColor: 'rgba(255, 255, 255, 0.1)' },
    });
    chartInstanceRef.current = chart;

    const lineSeries = chart.addSeries(LineSeries, {
      color: '#10b981',
      lineWidth: 2,
      priceFormat: {
        type: 'custom',
        formatter: (p: number) => p.toFixed(2),
      },
    });
    lineSeriesRef.current = lineSeries;

    const formattedPoints: LineData<Time>[] = result.equity_curve.map((p) => ({
      time: p.time as Time,
      value: p.value,
    }));

    lineSeries.setData(formattedPoints);
    chart.timeScale().fitContent();

    const handleResize = () => {
      if (container && chart) {
        chart.applyOptions({ width: container.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [result]);

  const metrics = result?.metrics;
  const totalTrades = metrics?.total_trades ?? 0;
  const tradesShown = result?.trades?.length ?? 0;
  void metrics?.cagr_pct;

  const counts = research?.verdict_counts;
  const survivors = counts?.SURVIVES_RESEARCH_VALIDATION ?? 0;

  const options =
    catalog.length > 0
      ? catalog
          .filter((s) => s.status !== 'UNAVAILABLE' && s.engine)
          .map((s) => ({ id: s.id as BacktestParams['strategy'], label: strategyLabel(s.id, catalog) }))
      : FALLBACK_STRATEGIES;

  if (view === 'methodology') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <button
          type="button"
          className="nav-btn"
          onClick={() => setView('lab')}
          style={{ alignSelf: 'flex-start' }}
        >
          ← Back to Strategy Lab
        </button>
        <MethodologyTab research={research} />
      </div>
    );
  }

  return (
    <div className="backtester-tab" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div
        style={{
          background: 'rgba(234, 179, 8, 0.08)',
          border: '1px solid rgba(234, 179, 8, 0.35)',
          borderRadius: 12,
          padding: '0.85rem 1rem',
          color: '#fde68a',
          fontSize: '0.82rem',
        }}
      >
        <strong>Research status:</strong> controlled discovery study →{' '}
        <strong>{survivors} survivors</strong>
        {counts
          ? ` (FAILED ${counts.FAILED ?? 0} · FRAGILE ${counts.FRAGILE ?? 0} · INSUFFICIENT_DATA ${counts.INSUFFICIENT_DATA ?? 0} · UNAVAILABLE ${counts.UNAVAILABLE ?? 0})`
          : ' (report loading…)'}
        . Single-run simulation is descriptive only — not OOS proof.
        Cost/slippage <strong>NOT_CONFIGURED</strong>; survivorship{' '}
        <strong>{research?.survivorship?.status ?? 'NOT_VALIDATED'}</strong>. No production BUY.
        <button
          type="button"
          onClick={() => setView('methodology')}
          style={{
            marginLeft: 12,
            background: 'transparent',
            border: '1px solid rgba(253, 230, 138, 0.4)',
            color: '#fde68a',
            borderRadius: 8,
            padding: '0.25rem 0.6rem',
            cursor: 'pointer',
            fontSize: '0.78rem',
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          <BookOpen size={14} /> Methodology & study
        </button>
      </div>

      {metaError && (
        <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>{metaError}</div>
      )}

      <div
        style={{
          background: 'rgba(15, 23, 42, 0.65)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '16px',
          padding: '1.5rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '1.25rem',
            flexWrap: 'wrap',
            gap: '1rem',
          }}
        >
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
              <PlayCircle size={28} style={{ color: '#10b981' }} />
              <h2 style={{ margin: 0, fontSize: '1.4rem', fontWeight: 700 }}>Strategy Lab</h2>
            </div>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Historical simulation on local stock_summary (exchange-reference adjusted; CA-spanning
              trades excluded). Gross returns only — fees/slippage not applied.
            </p>
            {selectedCatalog?.research_validation && (
              <p style={{ margin: '0.4rem 0 0', fontSize: '0.78rem', color: '#94a3b8' }}>
                Catalog validation:{' '}
                <strong style={{ color: '#fde68a' }}>
                  {selectedCatalog.research_validation.status}
                </strong>
                {Object.keys(horizonVerdicts).length > 0 && (
                  <>
                    {' '}
                    ·{' '}
                    {Object.entries(horizonVerdicts)
                      .map(([h, v]) => `${h}=${v}`)
                      .join(', ')}
                  </>
                )}
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={loading}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.75rem 1.5rem',
              borderRadius: '10px',
              background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)',
              color: '#ffffff',
              fontWeight: 700,
              fontSize: '0.9rem',
              border: 'none',
              cursor: loading ? 'wait' : 'pointer',
            }}
          >
            {loading ? <Loader2 size={18} className="spinning" /> : <PlayCircle size={18} />}
            <span>{loading ? 'Simulating…' : 'Run Simulation'}</span>
          </button>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '1rem',
            paddingTop: '1rem',
            borderTop: '1px solid rgba(255, 255, 255, 0.08)',
          }}
        >
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Strategy
            </label>
            <select
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as BacktestParams['strategy'])}
              className="filter-select"
              style={{ width: '100%', padding: '0.5rem', borderRadius: '8px' }}
            >
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Holding (sessions)
            </label>
            <input
              type="number"
              value={holdingDays}
              onChange={(e) => setHoldingDays(Number(e.target.value))}
              min={1}
              max={120}
              className="filter-input"
              style={{ width: '100%', padding: '0.5rem', borderRadius: '8px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Top-N
            </label>
            <input
              type="number"
              value={topN}
              onChange={(e) => setTopN(Number(e.target.value))}
              min={1}
              max={30}
              className="filter-input"
              style={{ width: '100%', padding: '0.5rem', borderRadius: '8px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Stop Loss % (0 = off)
            </label>
            <input
              type="number"
              value={stopLoss}
              onChange={(e) => setStopLoss(Number(e.target.value))}
              min={0}
              max={30}
              className="filter-input"
              style={{ width: '100%', padding: '0.5rem', borderRadius: '8px' }}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>
              Take Profit % (0 = off)
            </label>
            <input
              type="number"
              value={takeProfit}
              onChange={(e) => setTakeProfit(Number(e.target.value))}
              min={0}
              max={100}
              className="filter-input"
              style={{ width: '100%', padding: '0.5rem', borderRadius: '8px' }}
            />
          </div>
        </div>
      </div>

      {Object.keys(horizonVerdicts).length > 0 && (
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.45)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 12,
            padding: '0.85rem 1rem',
            fontSize: '0.8rem',
            color: '#cbd5e1',
          }}
        >
          <strong style={{ color: '#f1f5f9' }}>Locked study verdicts for this engine</strong>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: 8 }}>
            {Object.entries(horizonVerdicts).map(([h, v]) => (
              <span
                key={h}
                style={{
                  padding: '0.25rem 0.55rem',
                  borderRadius: 6,
                  background: v === 'SURVIVES_RESEARCH_VALIDATION' ? 'rgba(16,185,129,0.15)' : 'rgba(148,163,184,0.12)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  fontFamily: 'monospace',
                  fontSize: '0.72rem',
                }}
              >
                {h}: {v}
              </span>
            ))}
          </div>
          {researchForStrategy.length > 0 && researchForStrategy[0]?.verdict_reasons?.length ? (
            <p style={{ margin: '0.5rem 0 0', color: '#94a3b8', fontSize: '0.75rem' }}>
              Sample reasons: {researchForStrategy[0].verdict_reasons.slice(0, 3).join('; ')}
            </p>
          ) : null}
        </div>
      )}

      {error && (
        <div className="error-banner" style={{ padding: '1.25rem' }}>
          <ShieldAlert size={24} />
          <div>
            <h4 style={{ margin: 0 }}>Simulator Error</h4>
            <p style={{ margin: 0, fontSize: '0.85rem' }}>{error}</p>
          </div>
        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
        }}
      >
        <div className="stat-card" style={{ background: 'rgba(15, 23, 42, 0.55)', padding: '1.25rem', borderRadius: '14px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Total Strategy Return (gross)</div>
          <div
            style={{
              fontSize: '1.8rem',
              fontWeight: 800,
              marginTop: '0.35rem',
              color: (metrics?.total_return_pct ?? 0) >= 0 ? '#10b981' : '#ef4444',
            }}
          >
            {fmtMetric(metrics?.total_return_pct, { suffix: '%', signed: true })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            Not net tradable · not CAGR
          </div>
        </div>

        <div className="stat-card" style={{ background: 'rgba(15, 23, 42, 0.55)', padding: '1.25rem', borderRadius: '14px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Sharpe Ratio</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, marginTop: '0.35rem', color: '#38bdf8' }}>
            {fmtMetric(metrics?.sharpe_ratio)}
          </div>
        </div>

        <div className="stat-card" style={{ background: 'rgba(15, 23, 42, 0.55)', padding: '1.25rem', borderRadius: '14px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Max Drawdown</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, marginTop: '0.35rem', color: '#ef4444' }}>
            {metrics?.max_drawdown_pct != null ? `-${Math.abs(metrics.max_drawdown_pct)}%` : '—'}
          </div>
        </div>

        <div className="stat-card" style={{ background: 'rgba(15, 23, 42, 0.55)', padding: '1.25rem', borderRadius: '14px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Win Rate</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 800, marginTop: '0.35rem', color: '#facc15' }}>
            {fmtMetric(metrics?.win_rate_pct, { suffix: '%' })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            {totalTrades > 0 ? `${totalTrades} trades` : '—'}
          </div>
        </div>

        <div className="stat-card" style={{ background: 'rgba(15, 23, 42, 0.55)', padding: '1.25rem', borderRadius: '14px' }}>
          <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Benchmark Alpha</div>
          <div
            style={{
              fontSize: '1.8rem',
              fontWeight: 800,
              marginTop: '0.35rem',
              color: (metrics?.alpha_pct ?? 0) >= 0 ? '#10b981' : '#ef4444',
            }}
          >
            {fmtMetric(metrics?.alpha_pct, { suffix: '%', signed: true })}
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
            {metrics?.alpha_pct == null ? 'Unavailable (no benchmark)' : 'vs provided benchmark'}
          </div>
        </div>
      </div>

      <div
        style={{
          background: 'rgba(15, 23, 42, 0.55)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '16px',
          padding: '1.5rem',
        }}
      >
        <h3 style={{ margin: '0 0 0.35rem', fontSize: '1.15rem', fontWeight: 700 }}>
          Portfolio Equity Curve (Base 100)
        </h3>
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          Equal-weight by exit session
          {metrics?.holding_days != null ? ` · holding ${metrics.holding_days} sessions` : ''}
        </span>
        {result && (!result.equity_curve || result.equity_curve.length === 0) ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            No equity curve — zero trades in this run.
          </div>
        ) : (
          <div
            ref={chartContainerRef}
            style={{ width: '100%', height: '360px', marginTop: '0.75rem', borderRadius: '8px', overflow: 'hidden' }}
          />
        )}
      </div>

      {result && totalTrades === 0 && (
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.55)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '16px',
            padding: '1.5rem',
            color: 'var(--text-secondary)',
            fontSize: '0.9rem',
          }}
        >
          No simulated trades for this parameter set.
        </div>
      )}

      {result && result.trades && result.trades.length > 0 && (
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.55)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '16px',
            padding: '1.5rem',
          }}
        >
          <h3 style={{ margin: '0 0 1rem', fontSize: '1.05rem' }}>
            Trades ({tradesShown}
            {totalTrades > tradesShown ? ` of ${totalTrades}` : ''})
          </h3>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ color: '#94a3b8', textAlign: 'left' }}>
                  {['Entry', 'Exit', 'Ticker', 'Entry Px', 'Exit Px', 'Return %'].map((h) => (
                    <th key={h} style={{ padding: '0.45rem', borderBottom: '1px solid rgba(255,255,255,0.08)' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.trades.map((t, i) => (
                  <tr key={`${t.StockCode}-${t.EntryDate}-${i}`}>
                    <td style={{ padding: '0.4rem' }}>{t.EntryDate}</td>
                    <td style={{ padding: '0.4rem' }}>{t.ExitDate}</td>
                    <td
                      style={{ padding: '0.4rem', fontFamily: 'monospace', cursor: 'pointer', color: '#38bdf8' }}
                      onClick={() => onSelectStock(t.StockCode)}
                    >
                      {t.StockCode}
                    </td>
                    <td style={{ padding: '0.4rem', fontFamily: 'monospace' }}>{t.EntryPrice}</td>
                    <td style={{ padding: '0.4rem', fontFamily: 'monospace' }}>{t.ExitPrice}</td>
                    <td
                      style={{
                        padding: '0.4rem',
                        fontFamily: 'monospace',
                        color: t.ReturnPct >= 0 ? '#34d399' : '#f87171',
                      }}
                    >
                      {t.ReturnPct > 0 ? '+' : ''}
                      {t.ReturnPct}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
