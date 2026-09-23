import React, { useEffect, useState } from 'react';
import {
  computeTradingPlan,
  createAuthSession,
  fetchJournals,
  getStoredSessionId,
  saveJournal,
  saveTradingPlan,
  setStoredSessionId,
} from '../services/api';

const BIAS = ['Bullish', 'Sideway', 'Bearish', 'Buy', 'Sell', 'OK', 'NOK', 'Acc', 'Normal', 'Dist'];

export const TradingPlanTab: React.FC = () => {
  const [sessionId, setSessionId] = useState<string | null>(getStoredSessionId());
  const [plan, setPlan] = useState<Record<string, string | number>>({
    ticker: 'BBCA',
    tf_1d: 'Bullish',
    tf_15m: 'Sideway',
    tf_5m: 'Bullish',
    macd_bias: 'Bullish',
    volume_bias: 'Buy',
    supertrend_bias: 'Buy',
    ma5_ok: 'OK',
    ma20_ok: 'OK',
    ma50_ok: 'OK',
    vwap_ok: 'OK',
    broksum: 'Normal',
    entry_price: 9000,
    tp: 9500,
    cl: 8700,
  });
  const [computed, setComputed] = useState<any>(null);
  const [weekly, setWeekly] = useState<any>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const ensure = async (): Promise<string> => {
    const existing = getStoredSessionId();
    if (existing) {
      setSessionId(existing);
      return existing;
    }
    const created = await createAuthSession('trading-plan');
    const sid = created.session_id as string;
    setStoredSessionId(sid);
    setSessionId(sid);
    return sid;
  };

  useEffect(() => {
    void (async () => {
      try {
        const sid = await ensure();
        const j = await fetchJournals(sid);
        setWeekly(j.weekly);
      } catch {
        setWeekly(null);
      }
    })();
  }, []);

  const onCompute = async () => {
    const res = await computeTradingPlan(plan);
    setComputed(res);
  };

  const onSavePlan = async () => {
    const sid = await ensure();
    const body = { ...plan, ...(computed || {}) };
    await saveTradingPlan(sid, body);
    setMsg('Plan saved (private to session)');
  };

  const onSaveJournal = async () => {
    const sid = await ensure();
    await saveJournal(sid, {
      ticker: plan.ticker,
      entry_price: plan.entry_price,
      exit_price: Number(plan.tp),
      lots: 1,
      stop_price: plan.cl,
      emotion: 'tenang',
    });
    const j = await fetchJournals(sid);
    setWeekly(j.weekly);
    setMsg('Journal entry saved');
  };

  return (
    <div className="tab-panel active">
      <h2 style={{ marginTop: 0, color: '#f1f5f9' }}>Trading Plan & Journal</h2>
      <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
        Excel V1 semantics: 11 confirmations → Confirm Score → Result Auto. Lot×100. Auth:{' '}
        {sessionId ? 'local session' : 'pending'} (NOT_CONFIGURED IdP).
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 8 }}>
        {Object.keys(plan).map((key) => (
          <label key={key} style={{ color: '#94a3b8', fontSize: '0.75rem' }}>
            {key}
            {BIAS.some((b) => String(plan[key]).toLowerCase() === b.toLowerCase()) ||
            ['tf_1d', 'tf_15m', 'tf_5m', 'macd_bias', 'volume_bias', 'supertrend_bias', 'ma5_ok', 'ma20_ok', 'ma50_ok', 'vwap_ok', 'broksum'].includes(key) ? (
              <select
                className="form-control"
                value={String(plan[key])}
                onChange={(e) => setPlan((p) => ({ ...p, [key]: e.target.value }))}
              >
                {['Bullish', 'Sideway', 'Bearish', 'Buy', 'Sell', 'OK', 'NOK', 'Acc', 'Normal', 'Dist'].map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="form-control"
                value={String(plan[key])}
                onChange={(e) =>
                  setPlan((p) => ({
                    ...p,
                    [key]: key === 'ticker' ? e.target.value.toUpperCase() : e.target.value,
                  }))
                }
              />
            )}
          </label>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        <button type="button" className="nav-btn active" onClick={() => void onCompute()}>
          Compute Score / RR
        </button>
        <button type="button" className="nav-btn" onClick={() => void onSavePlan()}>
          Save Plan
        </button>
        <button type="button" className="nav-btn" onClick={() => void onSaveJournal()}>
          Save Sample Journal Exit@TP
        </button>
      </div>
      {computed && (
        <div className="glass-card" style={{ marginTop: 16, padding: '1rem' }}>
          <div>Confirm Score: <strong>{computed.confirm_score}</strong></div>
          <div>Result Auto: <strong>{computed.result_auto}</strong></div>
          <div>RR Planned: <strong>{computed.rr_planned ?? '—'}</strong></div>
        </div>
      )}
      {weekly && (
        <div className="glass-card" style={{ marginTop: 12, padding: '1rem', color: '#94a3b8', fontSize: '0.85rem' }}>
          Weekly: trades {weekly.total_trades ?? '—'} · win rate{' '}
          {weekly.win_rate_pct == null ? '—' : `${Number(weekly.win_rate_pct).toFixed(1)}%`} · net{' '}
          {weekly.total_pl_net == null ? '—' : weekly.total_pl_net}
        </div>
      )}
      {msg && <p style={{ color: '#34d399' }}>{msg}</p>}
    </div>
  );
};
