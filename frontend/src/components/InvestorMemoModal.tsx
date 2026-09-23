import React from 'react';
import { Printer, X, ShieldCheck, TrendingUp, Coins, Building, Award, CheckCircle } from 'lucide-react';
import type { Company } from '../types';

interface InvestorMemoModalProps {
  company: Company;
  onClose: () => void;
}

export const InvestorMemoModal: React.FC<InvestorMemoModalProps> = ({ company, onClose }) => {
  const currentPrice = company.close ?? company.previous_price ?? null;
  const score =
    company.score?.total != null && Number.isFinite(company.score.total)
      ? company.score.total
      : null;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="modal-overlay" style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.75)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000,
      padding: '1.5rem',
    }}>
      <div className="memo-container" style={{
        background: '#0a0e1a',
        border: '1px solid rgba(255, 255, 255, 0.15)',
        borderRadius: '16px',
        width: '100%',
        maxWidth: '820px',
        maxHeight: '90vh',
        overflowY: 'auto',
        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
      }}>
        {/* Screen Toolbar (Hidden when printing) */}
        <div className="no-print" style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '1rem 1.5rem',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          background: 'rgba(15, 23, 42, 0.8)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Award size={20} style={{ color: '#38bdf8' }} />
            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>Investment Memo</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <button
              onClick={handlePrint}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
                padding: '0.5rem 1rem',
                borderRadius: '8px',
                background: '#38bdf8',
                color: '#000',
                fontWeight: 700,
                fontSize: '0.85rem',
                border: 'none',
                cursor: 'pointer',
              }}
            >
              <Printer size={16} />
              <span>Print / Save PDF</span>
            </button>
            <button
              onClick={onClose}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                color: '#fff',
                padding: '0.5rem',
                borderRadius: '8px',
                cursor: 'pointer',
              }}
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Printable Memo Sheet */}
        <div id="printableMemo" style={{ padding: '2rem', color: '#f8fafc' }}>
          {/* Header Banner */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            borderBottom: '2px solid rgba(56, 189, 248, 0.4)',
            paddingBottom: '1.25rem',
            marginBottom: '1.5rem',
          }}>
            <div>
              <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '1px', color: '#38bdf8', fontWeight: 700 }}>
                RitelInsight Research Brief
              </div>
              <h1 style={{ margin: '0.35rem 0 0.2rem', fontSize: '2rem', fontWeight: 800 }}>
                {company.code} &mdash; {company.name}
              </h1>
              <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                Sector: <strong>{company.sector}</strong> {company.conglomerate ? `| Group: ${company.conglomerate}` : ''}
              </div>
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '1.8rem', fontWeight: 800, color: currentPrice != null && currentPrice > 0 ? '#10b981' : '#64748b', fontFamily: 'monospace' }}>
                {currentPrice != null && currentPrice > 0 ? `Rp ${currentPrice.toLocaleString()}` : '—'}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                As of {company.price_date || 'UNAVAILABLE'}
              </div>
              <div style={{
                display: 'inline-block',
                marginTop: '0.5rem',
                padding: '0.25rem 0.75rem',
                borderRadius: '20px',
                background: score == null ? 'rgba(148, 163, 184, 0.15)' : score >= 80 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(56, 189, 248, 0.2)',
                color: score == null ? '#94a3b8' : score >= 80 ? '#34d399' : '#38bdf8',
                fontWeight: 700,
                fontSize: '0.8rem',
                border: `1px solid ${score == null ? 'rgba(148, 163, 184, 0.35)' : score >= 80 ? 'rgba(16, 185, 129, 0.4)' : 'rgba(56, 189, 248, 0.4)'}`,
              }}>
                SMSS Score: {score != null ? `${score} / 100` : '—'}
              </div>
            </div>
          </div>

          {/* 4 Pillars Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem', marginBottom: '1.5rem' }}>
            {/* Fundamentals */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '1.25rem',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', color: '#38bdf8' }}>
                <TrendingUp size={18} />
                <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700 }}>1. Valuation & Profitability</h3>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem', fontSize: '0.85rem' }}>
                <div>Price-to-Earnings (PER): <strong>{company.per ? `${company.per}x` : '—'}</strong></div>
                <div>Price-to-Book (PBV): <strong>{company.price_bv ? `${company.price_bv}x` : '—'}</strong></div>
                <div>Return on Equity (ROE): <strong style={{ color: '#10b981' }}>{company.roe ? `${company.roe}%` : '—'}</strong></div>
                <div>Debt-to-Equity (DER): <strong>{company.de_ratio ? `${company.de_ratio}x` : '—'}</strong></div>
              </div>
            </div>

            {/* Dividend Health */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '1.25rem',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', color: '#eab308' }}>
                <Coins size={18} />
                <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700 }}>2. Dividend Quality & Cashflow</h3>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.6rem', fontSize: '0.85rem' }}>
                <div>Dividend Yield: <strong style={{ color: '#eab308' }}>{company.yield ? `${company.yield.toFixed(1)}%` : '—'}</strong></div>
                <div>Latest DPS: <strong>{company.dps ? `Rp ${company.dps.toLocaleString()}` : '—'}</strong></div>
                <div>Trap Risk Score: <strong style={{ color: '#94a3b8' }}>UNAVAILABLE</strong></div>
                <div>Status: <strong style={{ color: '#94a3b8' }}>UNAVAILABLE</strong></div>
              </div>
            </div>

            {/* Broker Attribution */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '1.25rem',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', color: '#10b981' }}>
                <ShieldCheck size={18} />
                <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700 }}>3. Broker Attribution</h3>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.85rem' }}>
                <div>Participant mapping: <strong>Unavailable</strong></div>
                <div>Broker-attribution delta: <strong>N/A</strong></div>
                <div style={{ color: '#94a3b8' }}>The current dataset does not verify broker-to-investor identities.</div>
              </div>
            </div>

            {/* Ownership & Control */}
            <div style={{
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '12px',
              padding: '1.25rem',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem', color: '#c084fc' }}>
                <Building size={18} />
                <h3 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 700 }}>4. Corporate Governance & Group</h3>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem', fontSize: '0.85rem' }}>
                <div>Controlling Group: <strong>{company.conglomerate || 'Independent / State-Owned'}</strong></div>
                <div>Blue Chip Status: <strong>{company.is_blue_chip ? 'Yes (LQ45 Tier-1)' : 'Mid-Cap Compounder'}</strong></div>
                <div>Board Centrality: <strong style={{ color: '#94a3b8' }}>UNAVAILABLE</strong></div>
              </div>
            </div>
          </div>

          {/* Bottom Executive Verdict */}
          <div style={{
            background: 'rgba(16, 185, 129, 0.08)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            borderRadius: '12px',
            padding: '1.25rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#10b981', fontWeight: 700, marginBottom: '0.35rem' }}>
              <CheckCircle size={18} />
              <span>Executive Investment Verdict</span>
            </div>
            <p style={{ margin: 0, fontSize: '0.85rem', lineHeight: 1.5, color: '#e2e8f0' }}>
              <strong>{company.code}</strong> shows fundamental durability
              {company.roe != null ? ` with an ROE of ${company.roe}%` : ''}.
              Broker-to-participant attribution is unavailable; this memo does not claim institutional buying.
              Review Audit Risk and Dilution Watch separately before any allocation decision.
            </p>
          </div>

          <div style={{ marginTop: '1.5rem', fontSize: '0.7rem', color: 'var(--text-secondary)', textAlign: 'center', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '0.75rem' }}>
            Disclaimer: Generated automatically by RitelInsight for research purposes only. Not personal investment advice.
          </div>
        </div>
      </div>
    </div>
  );
};
