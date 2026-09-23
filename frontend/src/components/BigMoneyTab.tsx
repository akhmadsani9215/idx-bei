import React, { useEffect, useState } from 'react';
import { AlertTriangle, Landmark } from 'lucide-react';
import { fetchBigMoney } from '../services/api';

interface BigMoneyTabProps {
  selectedTicker?: string;
}

export const BigMoneyTab: React.FC<BigMoneyTabProps> = ({ selectedTicker = 'BBCA' }) => {
  const [ticker, setTicker] = useState(selectedTicker);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async (code: string) => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchBigMoney(code));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setTicker(selectedTicker);
  }, [selectedTicker]);

  useEffect(() => {
    void load(ticker);
  }, [ticker]);

  const layers = data?.layers || {};

  return (
    <div className="tab-panel active">
      <h2 style={{ marginTop: 0, color: '#f1f5f9' }}>
        <Landmark size={18} style={{ marginRight: 8 }} />
        Big Money
      </h2>
      <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>
        Ownership / foreign aggregate / market-wide broker — never fabricated actor Fast-In/Out.
      </p>
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <input
          className="form-control"
          style={{ width: 120, textTransform: 'uppercase' }}
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === 'Enter' && void load(ticker)}
        />
        <button type="button" className="nav-btn active" onClick={() => void load(ticker)}>
          Load
        </button>
      </div>
      {loading && <p style={{ color: '#94a3b8' }}>Loading…</p>}
      {error && (
        <div className="error-banner">
          <AlertTriangle size={16} /> {error}
        </div>
      )}
      {data && (
        <div style={{ display: 'grid', gap: 12 }}>
          {Object.keys(layers).length === 0 && (
            <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>No Big Money layers returned.</p>
          )}
          {Object.entries(layers).map(([key, layer]: [string, any]) => (
            <div key={key} className="glass-card" style={{ padding: '1rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <strong style={{ color: '#e2e8f0', textTransform: 'uppercase' }}>{key}</strong>
                <span style={{ color: '#fbbf24', fontFamily: 'monospace' }}>{layer?.status}</span>
              </div>
              <p style={{ color: '#94a3b8', fontSize: '0.8rem', margin: '0.5rem 0 0' }}>
                {layer?.message || layer?.note || layer?.reason || '—'}
              </p>
              {layer?.basis && (
                <p style={{ color: '#64748b', fontSize: '0.75rem' }}>Basis: {layer.basis}</p>
              )}
              {layer?.scope && (
                <p style={{ color: '#64748b', fontSize: '0.75rem' }}>Scope: {layer.scope}</p>
              )}
              {layer?.concentration && (
                <pre style={{ color: '#cbd5e1', fontSize: '0.72rem', whiteSpace: 'pre-wrap' }}>
                  {JSON.stringify(layer.concentration, null, 2)}
                </pre>
              )}
              {Array.isArray(layer?.top_holders) && layer.top_holders.length > 0 && (
                <ul style={{ color: '#94a3b8', fontSize: '0.75rem', margin: '0.4rem 0 0' }}>
                  {layer.top_holders.slice(0, 5).map((h: any, i: number) => (
                    <li key={i}>
                      {h.investor || '—'} · {h.pct == null ? '—' : `${h.pct}%`} ({h.basis || 'disclosure'})
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
          <div className="glass-card" style={{ padding: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong style={{ color: '#e2e8f0', textTransform: 'uppercase' }}>Fast-In / Fast-Out</strong>
              <span style={{ color: '#fbbf24', fontFamily: 'monospace' }}>
                {data?.fast_in_fast_out || data?.layers?.fast_in_fast_out?.status || 'UNAVAILABLE'}
              </span>
            </div>
            <p style={{ color: '#94a3b8', fontSize: '0.8rem', margin: '0.5rem 0 0' }}>
              Transaction-based actor Fast-In/Out requires verified tape — not inferred from disclosure or aggregates.
            </p>
          </div>
          {data?.data_inventory && (
            <div className="glass-card" style={{ padding: '1rem', fontSize: '0.75rem', color: '#94a3b8' }}>
              <strong style={{ color: '#e2e8f0' }}>Data inventory</strong>
              <pre style={{ margin: '0.4rem 0 0', whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(data.data_inventory, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
