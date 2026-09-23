import React, { useState, useEffect, useCallback } from 'react';
import {
  Database,
  Calendar,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Copy,
  Check,
  HardDrive,
  Layers,
  TrendingUp,
  Play,
  Clock,
} from 'lucide-react';
import { fetchIngestionStatus, triggerIngestion } from '../services/api';
import type { IngestionStatusResponse, BackfillTier, FreshnessStatus, OrchestrationPipeline } from '../types';

interface IngestionTabProps {
  lastLiveEvent?: any;
}

export const IngestionTab: React.FC<IngestionTabProps> = ({ lastLiveEvent }) => {
  const [data, setData] = useState<IngestionStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<string | null>(null);
  const [selectedTier, setSelectedTier] = useState<number>(2); // Default to Tier 2 Recommended
  const [isTriggering, setIsTriggering] = useState<boolean>(false);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<{ id: string; progress: number; message: string } | null>(null);
  const [histStart, setHistStart] = useState<string>('');
  const [histEnd, setHistEnd] = useState<string>('');
  const [ownershipPath, setOwnershipPath] = useState<string>('');

  const loadStatus = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchIngestionStatus();
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to load ingestion status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  // Listen to WebSocket events for live ingestion updates
  useEffect(() => {
    if (!lastLiveEvent) return;
    if (lastLiveEvent.type === 'ingestion_progress') {
      setActiveJob({
        id: lastLiveEvent.job_id,
        progress: lastLiveEvent.progress,
        message: lastLiveEvent.message,
      });
    } else if (lastLiveEvent.type === 'ingestion_completed') {
      setActiveJob(null);
      const overall = lastLiveEvent.overall_status;
      setTriggerMessage(
        overall
          ? `Job finished — overall status: ${overall}`
          : (lastLiveEvent.message || 'Ingestion task completed.'),
      );
      loadStatus();
    } else if (lastLiveEvent.type === 'ingestion_error') {
      setActiveJob(null);
      setError(`Ingestion error: ${lastLiveEvent.error || 'unknown error'}`);
    }
  }, [lastLiveEvent, loadStatus]);

  // Robust polling fallback in case WebSocket is blocked or disconnected
  useEffect(() => {
    if (!activeJob) return;
    const interval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/system/jobs/${activeJob.id}`);
        if (resp.ok) {
          const job = await resp.json();
          if (job.status === 'completed') {
            setActiveJob(null);
            setTriggerMessage(job.message || 'Ingestion completed.');
            loadStatus();
          } else if (job.status === 'failed') {
            setActiveJob(null);
            setError(`Job failed: ${job.message || 'unknown error'}`);
          } else {
            setActiveJob({
              id: job.job_id,
              progress: typeof job.progress_pct === 'number' ? job.progress_pct : 0,
              message: job.message || 'Processing ingestion...',
            });
          }
        }
      } catch {
        // ignore network hiccups
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [activeJob, loadStatus]);

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(id);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const handleTriggerSyncAll = async () => {
    try {
      setIsTriggering(true);
      setTriggerMessage(null);
      setError(null);
      const res = await triggerIngestion({ job_type: 'sync_all' });
      setActiveJob({
        id: res.job_id,
        progress: 10,
        message: 'Sync All Data orchestrator scheduled...',
      });
      setTriggerMessage('Sync All Data started in background. Pipeline statuses update when the job finishes.');
    } catch (err: any) {
      setError(err.message || 'Failed to trigger Sync All Data');
    } finally {
      setIsTriggering(false);
    }
  };

  const handleTriggerHistorical = async () => {
    if (!histStart.trim() || !histEnd.trim()) {
      setError('Historical backfill requires explicit start and end dates (YYYY-MM-DD or YYYYMMDD).');
      return;
    }
    try {
      setIsTriggering(true);
      setTriggerMessage(null);
      setError(null);
      const res = await triggerIngestion({
        job_type: 'backfill',
        start_date: histStart.trim(),
        end_date: histEnd.trim(),
        concurrency: 4,
      });
      setActiveJob({
        id: res.job_id,
        progress: 10,
        message: `Historical backfill ${histStart} → ${histEnd} scheduled...`,
      });
      setTriggerMessage(`Historical backfill job started (${histStart} → ${histEnd}).`);
    } catch (err: any) {
      setError(err.message || 'Failed to trigger historical backfill');
    } finally {
      setIsTriggering(false);
    }
  };

  const handleTriggerOwnership = async () => {
    if (!ownershipPath.trim()) {
      setError('Ownership ingest requires an explicit local CSV path or http(s) URL.');
      return;
    }
    try {
      setIsTriggering(true);
      setTriggerMessage(null);
      setError(null);
      const res = await triggerIngestion({
        job_type: 'ownership',
        path_or_url: ownershipPath.trim(),
      });
      setActiveJob({
        id: res.job_id,
        progress: 10,
        message: 'Ownership ingest scheduled...',
      });
      setTriggerMessage('Ownership ingest started from the provided path/URL.');
    } catch (err: any) {
      setError(err.message || 'Failed to trigger ownership ingest');
    } finally {
      setIsTriggering(false);
    }
  };

  const handleTriggerDaily = async () => {
    try {
      setIsTriggering(true);
      setTriggerMessage(null);
      const res = await triggerIngestion({ job_type: 'daily' });
      setActiveJob({ id: res.job_id, progress: 10, message: 'Daily market ingestion scheduled...' });
      setTriggerMessage('Daily market close ingestion started in background.');
    } catch (err: any) {
      setError(err.message || 'Failed to trigger daily ingestion');
    } finally {
      setIsTriggering(false);
    }
  };

  const handleTriggerTier = async (tier: BackfillTier | undefined) => {
    if (!tier) {
      setError('No backfill tier available to trigger.');
      return;
    }
    if (tier.trading_days_to_fetch === 0) {
      setTriggerMessage(`${tier.name} is already 100% up to date with zero missing trading sessions!`);
      return;
    }
    try {
      setIsTriggering(true);
      setTriggerMessage(null);
      const startStr = tier.target_range.start.replace(/-/g, '');
      const endStr = tier.target_range.end.replace(/-/g, '');
      const res = await triggerIngestion({
        job_type: 'backfill',
        start_date: startStr,
        end_date: endStr,
        concurrency: 8,
      });
      setActiveJob({
        id: res.job_id,
        progress: 10,
        message: `Backfill ${tier.name} started in background...`,
      });
      setTriggerMessage(`Backfill job (${startStr} → ${endStr}) started in background.`);
    } catch (err: any) {
      setError(err.message || 'Failed to trigger backfill');
    } finally {
      setIsTriggering(false);
    }
  };

  if (loading && !data) {
    return (
      <div style={{ textAlign: 'center', padding: '5rem 0', color: 'var(--text-secondary)' }}>
        <RefreshCw size={36} className="spin" style={{ margin: '0 auto 1rem', display: 'block', color: 'var(--accent-blue)' }} />
        <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>Analyzing timeseries partitions and dataset health...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="error-banner" style={{ margin: '2rem 0' }}>
        <AlertTriangle size={48} />
        <h2>Data Ingestion Status Unavailable</h2>
        <p>{error}</p>
        <button className="primary-btn" onClick={loadStatus} style={{ marginTop: '1rem' }}>
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;

  const inv = data.inventory;
  const gaps = data.gaps;
  const recs = data.recommendations;
  const freshness = data.freshness;
  const missingDays: string[] = Array.isArray(gaps?.true_missing_trading_days)
    ? gaps.true_missing_trading_days
    : [];
  const missingCount = gaps?.true_missing_trading_days_count ?? missingDays.length;
  const activeTierObj =
    (Array.isArray(recs?.tiers) && recs.tiers.find((t) => t.tier === selectedTier)) ||
    (Array.isArray(recs?.tiers) ? recs.tiers[1] : undefined);
  const fxQuote = inv?.system?.usd_idr;

  const getStatusColor = (status: string) => {
    if (status === 'healthy') return '#22c55e';
    if (status === 'warning') return '#eab308';
    return '#ef4444';
  };

  const getFreshnessColor = (status: FreshnessStatus) => {
    if (status === 'current') return '#22c55e';
    if (status === 'screener_stale' || status === 'screener_missing') return '#eab308';
    return '#94a3b8';
  };

  const formatTs = (value: string | null | undefined) => {
    if (!value) return 'Not available';
    return value.replace('T', ' ').slice(0, 19);
  };

  const freshnessLabel = (status: FreshnessStatus) => {
    if (status === 'current') return 'Current';
    if (status === 'screener_stale') return 'Screener lagging';
    if (status === 'screener_missing') return 'Screener missing';
    return 'Unknown';
  };

  const orch = data.orchestration;
  const pipelines: OrchestrationPipeline[] = Array.isArray(orch?.pipelines) ? orch.pipelines : [];
  const integrations = orch?.integrations || {};
  const lastSync = orch?.last_sync_all;
  const overallSync = lastSync?.overall_status;

  const pipelineStatusColor = (status: string) => {
    const s = (status || '').toUpperCase();
    if (s === 'SUCCESS') return '#22c55e';
    if (s === 'PARTIAL' || s === 'RUNNING') return '#eab308';
    if (s === 'FAILED') return '#ef4444';
    if (s === 'UNAVAILABLE') return '#64748b';
    return '#94a3b8';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Top Banner: Ingestion Health & Executive Summary */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(30, 41, 59, 0.85) 100%)',
          borderRadius: '16px',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          padding: '1.75rem 2rem',
          display: 'flex',
          flexWrap: 'wrap',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1.5rem',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <div
            style={{
              width: '60px',
              height: '60px',
              borderRadius: '14px',
              background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.15) 0%, rgba(14, 165, 233, 0.25) 100%)',
              border: '1px solid rgba(56, 189, 248, 0.3)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#38bdf8',
            }}
          >
            <Database size={32} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
              <h1 style={{ fontSize: '1.6rem', fontWeight: 800, color: '#f8fafc', margin: 0, letterSpacing: '-0.5px' }}>
                RitelInsight Data Center
              </h1>
              <span
                style={{
                  padding: '0.25rem 0.75rem',
                  borderRadius: '20px',
                  fontSize: '0.75rem',
                  fontWeight: 800,
                  textTransform: 'uppercase',
                  background: `${getStatusColor(data.status)}22`,
                  color: getStatusColor(data.status),
                  border: `1px solid ${getStatusColor(data.status)}44`,
                }}
              >
                {data.status}
              </span>
            </div>
            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Pipeline orchestration and monitoring for available data sources — no fabricated connectivity.
            </p>
          </div>
        </div>

        {/* Action Buttons & Health Gauge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'uppercase', fontWeight: 700 }}>
              Dataset Health Score
            </div>
            <div style={{ fontSize: '1.75rem', fontWeight: 800, color: getStatusColor(data.status) }}>
              {data.health_score} <span style={{ fontSize: '1rem', color: 'var(--text-secondary)' }}>/ 100</span>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
            <button
              onClick={loadStatus}
              disabled={loading}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.65rem 1rem',
                borderRadius: '10px',
                background: 'rgba(255, 255, 255, 0.05)',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                color: '#f8fafc',
                cursor: 'pointer',
                fontWeight: 600,
                fontSize: '0.85rem',
              }}
            >
              <RefreshCw size={15} className={loading ? 'spin' : ''} />
              <span>Refresh</span>
            </button>

            <button
              onClick={handleTriggerSyncAll}
              disabled={isTriggering || activeJob !== null}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.65rem 1.25rem',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #059669 0%, #34d399 100%)',
                border: 'none',
                color: '#fff',
                cursor: isTriggering || activeJob ? 'not-allowed' : 'pointer',
                fontWeight: 700,
                fontSize: '0.85rem',
                boxShadow: '0 4px 15px rgba(52, 211, 153, 0.3)',
              }}
            >
              <Play size={15} fill="#fff" />
              <span>SYNC ALL DATA</span>
            </button>

            <button
              onClick={handleTriggerDaily}
              disabled={isTriggering || activeJob !== null}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.65rem 1.25rem',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #0284c7 0%, #38bdf8 100%)',
                border: 'none',
                color: '#fff',
                cursor: isTriggering || activeJob ? 'not-allowed' : 'pointer',
                fontWeight: 700,
                fontSize: '0.85rem',
                boxShadow: '0 4px 15px rgba(56, 189, 248, 0.3)',
              }}
            >
              <Play size={15} fill="#fff" />
              <span>Sync Market Close</span>
            </button>
          </div>
        </div>
      </div>

      {/* Active Ingestion Job Progress Bar */}
      {activeJob && (
        <div
          style={{
            background: 'rgba(2, 132, 199, 0.12)',
            border: '1px solid rgba(56, 189, 248, 0.3)',
            borderRadius: '12px',
            padding: '1rem 1.5rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
            <span style={{ fontWeight: 700, color: '#38bdf8', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <RefreshCw size={16} className="spin" />
              {activeJob.message}
            </span>
            <span style={{ fontWeight: 800, color: '#f8fafc', fontSize: '0.9rem' }}>{activeJob.progress}%</span>
          </div>
          <div style={{ width: '100%', height: '8px', background: 'rgba(255, 255, 255, 0.1)', borderRadius: '4px', overflow: 'hidden' }}>
            <div
              style={{
                width: `${activeJob.progress}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #0284c7, #38bdf8)',
                transition: 'width 0.4s ease',
              }}
            />
          </div>
        </div>
      )}

      {triggerMessage && !activeJob && (
        <div
          style={{
            background: 'rgba(34, 197, 94, 0.1)',
            border: '1px solid rgba(34, 197, 94, 0.3)',
            borderRadius: '12px',
            padding: '0.85rem 1.25rem',
            color: '#4ade80',
            fontSize: '0.85rem',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}
        >
          <CheckCircle2 size={16} />
          <span>{triggerMessage}</span>
        </div>
      )}

      {error && data && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.35)',
            borderRadius: '12px',
            padding: '0.85rem 1.25rem',
            color: '#fca5a5',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}
        >
          {error}
        </div>
      )}

      {/* Integration honesty + pipeline orchestration */}
      <div
        style={{
          background: 'rgba(15, 23, 42, 0.7)',
          borderRadius: '14px',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          padding: '1.5rem',
        }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: '1rem', marginBottom: '1.25rem' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc' }}>
              Pipeline Orchestration
            </h2>
            <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              Overall Sync All:{' '}
              <strong style={{ color: pipelineStatusColor(String(overallSync || 'IDLE')) }}>
                {overallSync || 'IDLE'}
              </strong>
              {lastSync?.completed_at ? ` · last finished ${formatTs(lastSync.completed_at)}` : ''}
            </p>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {([
              ['Realtime', integrations.realtime],
              ['AI', integrations.ai],
              ['Telegram', integrations.telegram],
              ['Payment', integrations.payment],
            ] as const).map(([label, status]) => (
              <span
                key={label}
                style={{
                  padding: '0.35rem 0.7rem',
                  borderRadius: '8px',
                  fontSize: '0.72rem',
                  fontWeight: 700,
                  letterSpacing: '0.02em',
                  background: 'rgba(100, 116, 139, 0.2)',
                  color: '#94a3b8',
                  border: '1px solid rgba(148, 163, 184, 0.25)',
                }}
              >
                {label}: {status || 'NOT_CONFIGURED'}
              </span>
            ))}
          </div>
        </div>

        {fxQuote && (
          <div
            style={{
              marginBottom: '1rem',
              padding: '0.75rem 1rem',
              borderRadius: 8,
              border: '1px solid rgba(148, 163, 184, 0.25)',
              background: 'rgba(15, 23, 42, 0.45)',
              fontSize: '0.78rem',
              color: '#cbd5e1',
            }}
          >
            <strong style={{ color: '#e2e8f0' }}>USD/IDR FX</strong>
            {': '}
            {fxQuote.rate != null ? fxQuote.rate : '—'}
            {' · '}
            status={fxQuote.status || 'unknown'}
            {' · '}
            {fxQuote.is_market_quote
              ? 'market-quote (cached/live — not verified commercial)'
              : fxQuote.is_default_constant
                ? 'DEFAULT CONSTANT — not a market quote'
                : 'not a verified market quote'}
            {fxQuote.source ? ` · source=${fxQuote.source}` : ''}
            {fxQuote.last_updated ? ` · as_of=${fxQuote.last_updated}` : ''}
          </div>
        )}

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '0.85rem',
          }}
        >
          {pipelines.map((p) => {
            const st = String(p.status || 'IDLE');
            const color = pipelineStatusColor(st);
            const warnings = Array.isArray(p.warnings) ? p.warnings : [];
            const errors = Array.isArray(p.errors) ? p.errors : [];
            return (
              <div
                key={p.id}
                style={{
                  background: 'rgba(2, 6, 23, 0.55)',
                  border: `1px solid ${color}33`,
                  borderRadius: '12px',
                  padding: '1rem',
                  minHeight: '140px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <div style={{ fontWeight: 700, color: '#e2e8f0', fontSize: '0.9rem' }}>{p.label}</div>
                  <span style={{ fontSize: '0.7rem', fontWeight: 800, color }}>{st}</span>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                  <div>Availability: {p.availability || '—'}</div>
                  <div>Source: {p.source || '—'}</div>
                  <div>Records: {p.records == null ? '—' : p.records}</div>
                  <div>Quality: {p.quality == null || p.quality === '' ? '—' : String(p.quality)}</div>
                  <div>Updated: {formatTs(p.completed_at)}</div>
                  {p.duration_sec != null && <div>Duration: {p.duration_sec}s</div>}
                </div>
                {warnings.length > 0 && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: '#fbbf24' }}>
                    {warnings.slice(0, 2).join(' · ')}
                  </div>
                )}
                {errors.length > 0 && (
                  <div style={{ marginTop: '0.35rem', fontSize: '0.72rem', color: '#f87171' }}>
                    {errors.slice(0, 2).join(' · ')}
                  </div>
                )}
              </div>
            );
          })}
          {pipelines.length === 0 && (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
              Orchestration catalog not yet available from API.
            </div>
          )}
        </div>

        {/* Parameterized Historical + Ownership (manual; not Sync All) */}
        <div
          style={{
            marginTop: '1.25rem',
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: '1rem',
          }}
        >
          <div
            style={{
              background: 'rgba(2, 6, 23, 0.45)',
              border: '1px solid rgba(234, 179, 8, 0.25)',
              borderRadius: '12px',
              padding: '1rem',
            }}
          >
            <div style={{ fontWeight: 700, color: '#f8fafc', marginBottom: '0.35rem' }}>
              Historical — Manual Backfill
            </div>
            <div style={{ fontSize: '0.75rem', color: '#fbbf24', marginBottom: '0.75rem' }}>
              PARTIAL · requires explicit date range · not in Sync All
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <input
                type="text"
                placeholder="Start (YYYY-MM-DD or YYYYMMDD)"
                value={histStart}
                onChange={(e) => setHistStart(e.target.value)}
                className="filter-input"
                style={{ padding: '0.5rem', borderRadius: '8px' }}
              />
              <input
                type="text"
                placeholder="End (YYYY-MM-DD or YYYYMMDD)"
                value={histEnd}
                onChange={(e) => setHistEnd(e.target.value)}
                className="filter-input"
                style={{ padding: '0.5rem', borderRadius: '8px' }}
              />
              <button
                onClick={handleTriggerHistorical}
                disabled={isTriggering || activeJob !== null}
                style={{
                  padding: '0.55rem 0.9rem',
                  borderRadius: '8px',
                  border: 'none',
                  background: '#ca8a04',
                  color: '#fff',
                  fontWeight: 700,
                  cursor: isTriggering || activeJob ? 'not-allowed' : 'pointer',
                }}
              >
                Run Historical Backfill
              </button>
            </div>
          </div>

          <div
            style={{
              background: 'rgba(2, 6, 23, 0.45)',
              border: '1px solid rgba(100, 116, 139, 0.35)',
              borderRadius: '12px',
              padding: '1rem',
            }}
          >
            <div style={{ fontWeight: 700, color: '#f8fafc', marginBottom: '0.35rem' }}>
              Ownership — Parameterized Ingest
            </div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '0.75rem' }}>
              UNAVAILABLE for Sync All · requires explicit CSV path or http(s) URL · no default source
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              <input
                type="text"
                placeholder="path_or_url (local file or https://...)"
                value={ownershipPath}
                onChange={(e) => setOwnershipPath(e.target.value)}
                className="filter-input"
                style={{ padding: '0.5rem', borderRadius: '8px' }}
              />
              <button
                onClick={handleTriggerOwnership}
                disabled={isTriggering || activeJob !== null}
                style={{
                  padding: '0.55rem 0.9rem',
                  borderRadius: '8px',
                  border: 'none',
                  background: '#475569',
                  color: '#fff',
                  fontWeight: 700,
                  cursor: isTriggering || activeJob ? 'not-allowed' : 'pointer',
                }}
              >
                Run Ownership Ingest
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Freshness Contract */}
      {freshness && (
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.7)',
            borderRadius: '14px',
            border: freshness.screener_lagging
              ? '1px solid rgba(234, 179, 8, 0.45)'
              : '1px solid rgba(255, 255, 255, 0.07)',
            padding: '1.5rem 1.75rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              flexWrap: 'wrap',
              gap: '0.75rem',
              marginBottom: '1.25rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <Clock size={20} style={{ color: getFreshnessColor(freshness.status) }} />
              <div>
                <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
                  Data Freshness
                </h2>
                <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  Compares last completed ingestion evidence, market partitions, and screener snapshot age.
                </p>
              </div>
            </div>
            <span
              style={{
                padding: '0.3rem 0.75rem',
                borderRadius: '20px',
                fontSize: '0.75rem',
                fontWeight: 800,
                textTransform: 'uppercase',
                background: `${getFreshnessColor(freshness.status)}22`,
                color: getFreshnessColor(freshness.status),
                border: `1px solid ${getFreshnessColor(freshness.status)}55`,
              }}
            >
              {freshnessLabel(freshness.status)}
            </span>
          </div>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
              gap: '1rem',
              marginBottom: freshness.warning ? '1rem' : 0,
            }}
          >
            <div
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '10px',
                padding: '1rem',
              }}
            >
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700 }}>
                Ingestion last success
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc', marginTop: '0.35rem' }}>
                {freshness.last_successful_ingestion.available
                  ? formatTs(freshness.last_successful_ingestion.completed_at)
                  : 'No completed job in this session'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
                {freshness.last_successful_ingestion.available
                  ? `${freshness.last_successful_ingestion.job_type || 'job'} · ${freshness.last_successful_ingestion.job_id}`
                  : freshness.last_successful_ingestion.note || 'Job registry is process-local.'}
              </div>
            </div>

            <div
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '10px',
                padding: '1rem',
              }}
            >
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700 }}>
                Market data as-of
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#38bdf8', marginTop: '0.35rem' }}>
                {freshness.market_data.as_of_date || 'No partitions'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
                stock_summary last partition
                {freshness.ingestion_evidence_at
                  ? ` · evidence ${formatTs(freshness.ingestion_evidence_at)}`
                  : ''}
              </div>
            </div>

            <div
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '10px',
                padding: '1rem',
              }}
            >
              <div style={{ fontSize: '0.7rem', color: '#94a3b8', textTransform: 'uppercase', fontWeight: 700 }}>
                Screener snapshot as-of
              </div>
              <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc', marginTop: '0.35rem' }}>
                {freshness.screener_snapshot.exists
                  ? formatTs(
                      freshness.screener_snapshot.content_last_updated ||
                        freshness.screener_snapshot.modified_iso
                    )
                  : 'File missing'}
              </div>
              <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.25rem' }}>
                {freshness.screener_snapshot.file}
                {freshness.screener_snapshot.modified_iso
                  ? ` · mtime ${formatTs(freshness.screener_snapshot.modified_iso)}`
                  : ''}
              </div>
            </div>
          </div>

          {freshness.warning && (
            <div
              style={{
                background: 'rgba(234, 179, 8, 0.1)',
                border: '1px solid rgba(234, 179, 8, 0.35)',
                borderRadius: '10px',
                padding: '0.85rem 1rem',
                color: '#fbbf24',
                fontSize: '0.85rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.5rem',
              }}
            >
              <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>{freshness.warning}</span>
            </div>
          )}
        </div>
      )}

      {/* 2-Column Grid: Section 1 & 2 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: '1.5rem' }}>
        {/* 1. Partitioned Timeseries Storage */}
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.7)',
            borderRadius: '14px',
            border: '1px solid rgba(255, 255, 255, 0.07)',
            padding: '1.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1.25rem' }}>
            <HardDrive size={20} style={{ color: '#38bdf8' }} />
            <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
              Partitioned Timeseries (O(1) Daily Ingestion)
            </h2>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {Object.entries(inv?.timeseries || {}).map(([ds, meta]) => (
              <div
                key={ds}
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  border: '1px solid rgba(255, 255, 255, 0.05)',
                  borderRadius: '10px',
                  padding: '1rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <div>
                  <div style={{ fontWeight: 700, color: '#f8fafc', fontSize: '0.95rem', textTransform: 'capitalize' }}>
                    {ds.replace('_', ' ')}
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                    Coverage: {meta.start_date || 'N/A'} → {meta.end_date || 'N/A'}
                  </div>
                  <div style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.2rem' }}>
                    {meta.daily_partitions_count} daily partitions &bull; {meta.compacted_partitions_count} monthly compacted
                  </div>
                </div>

                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#38bdf8' }}>
                    {meta.total_dates} <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>days</span>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 600 }}>
                    {meta.total_size_mb} MB
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 2. Consolidated Parquet & Snapshots */}
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.7)',
            borderRadius: '14px',
            border: '1px solid rgba(255, 255, 255, 0.07)',
            padding: '1.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '1.25rem' }}>
            <Layers size={20} style={{ color: '#a855f7' }} />
            <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
              Consolidated Parquet & Fundamental Snapshots
            </h2>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {/* Parquet table rows */}
            {Object.entries(inv?.parquet_exports || {}).map(([name, meta]) => (
              <div
                key={name}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <div
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: meta.exists ? '#22c55e' : '#ef4444',
                    }}
                  />
                  <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0' }}>
                    {name}.parquet
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.8rem' }}>
                  <span style={{ color: '#94a3b8' }}>{meta.row_count.toLocaleString()} rows</span>
                  <span style={{ color: '#38bdf8', fontWeight: 700 }}>{meta.size_mb} MB</span>
                </div>
              </div>
            ))}

            {/* Listed companies & Profiles summary */}
            <div
              style={{
                marginTop: '0.5rem',
                padding: '0.85rem',
                borderRadius: '8px',
                background: 'rgba(168, 85, 247, 0.08)',
                border: '1px solid rgba(168, 85, 247, 0.2)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#e9d5ff' }}>
                  Company Profiles & Governance
                </div>
                <div style={{ fontSize: '0.75rem', color: '#c084fc' }}>
                  {inv.fundamental_snapshots.detailed_profiles_scraped} / {inv.fundamental_snapshots.total_listed_companies} companies with board, shareholders, & subsidiaries
                </div>
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 800, color: '#c084fc' }}>
                {inv.fundamental_snapshots.profile_coverage_pct}%
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Calendar Gap Detection & Missing Sessions */}
      <div
        style={{
          background: 'rgba(15, 23, 42, 0.7)',
          borderRadius: '14px',
          border: '1px solid rgba(255, 255, 255, 0.07)',
          padding: '1.5rem 2rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
            <Calendar size={20} style={{ color: '#f59e0b' }} />
            <div>
              <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
                2026 Calendar Gap Analysis & Trading Session Health
              </h2>
              <p style={{ margin: 0, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                Cross-checks expected trading days against 18 official IDX public holidays and actual ingested partitions.
              </p>
            </div>
          </div>

          <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Total Weekdays</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f8fafc' }}>{gaps.total_calendar_weekdays}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Official Holidays</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#94a3b8' }}>{gaps.official_holidays_count}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Ingested Sessions</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#22c55e' }}>{gaps.ingested_days}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Missing Sessions</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: missingCount > 0 ? '#ef4444' : '#22c55e' }}>
                {missingCount}
              </div>
            </div>
          </div>
        </div>

        {/* Missing Dates Alert Box */}
        {missingCount > 0 ? (
          <div
            style={{
              background: 'rgba(239, 68, 68, 0.08)',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              borderRadius: '10px',
              padding: '1.25rem',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem', marginBottom: '0.75rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: '#f87171', fontWeight: 700, fontSize: '0.9rem' }}>
                <AlertTriangle size={18} />
                <span>Detected {missingCount} un-ingested trading sessions in 2026:</span>
              </div>
              <button
                onClick={() => handleTriggerTier(Array.isArray(recs?.tiers) ? recs.tiers[0] : undefined)}
                disabled={isTriggering || activeJob !== null}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  padding: '0.45rem 0.9rem',
                  borderRadius: '8px',
                  background: '#ef4444',
                  border: 'none',
                  color: '#fff',
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                <RefreshCw size={13} className={isTriggering ? 'spin' : ''} />
                <span>Auto-Repair 2026 Gaps</span>
              </button>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
              {missingDays.map((date) => (
                <span
                  key={date}
                  style={{
                    padding: '0.3rem 0.65rem',
                    borderRadius: '6px',
                    background: 'rgba(239, 68, 68, 0.2)',
                    border: '1px solid rgba(239, 68, 68, 0.4)',
                    color: '#fca5a5',
                    fontSize: '0.8rem',
                    fontFamily: 'monospace',
                    fontWeight: 700,
                  }}
                >
                  {date}
                </span>
              ))}
            </div>
          </div>
        ) : (
          <div
            style={{
              background: 'rgba(34, 197, 94, 0.08)',
              border: '1px solid rgba(34, 197, 94, 0.25)',
              borderRadius: '10px',
              padding: '1rem',
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              color: '#4ade80',
              fontSize: '0.9rem',
              fontWeight: 600,
            }}
          >
            <CheckCircle2 size={20} />
            <span>All 2026 weekday trading sessions have been fully ingested with zero gaps.</span>
          </div>
        )}
      </div>

      {/* 4. Strategic Backfill Recommendation Engine */}
      <div
        style={{
          background: 'rgba(15, 23, 42, 0.85)',
          borderRadius: '16px',
          border: '1px solid rgba(56, 189, 248, 0.2)',
          padding: '2rem',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.35)',
        }}
      >
        <div style={{ marginBottom: '1.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
            <TrendingUp size={24} style={{ color: '#38bdf8' }} />
            <h2 style={{ fontSize: '1.35rem', fontWeight: 800, color: '#f8fafc', margin: 0 }}>
              How Much Should We Backfill? (Quantitative Horizon Guide)
            </h2>
          </div>
          <p style={{ margin: 0, color: '#cbd5e1', fontSize: '0.92rem', lineHeight: '1.5' }}>
            {recs.summary.recommended_action}
          </p>
        </div>

        {/* 4 Tier Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginBottom: '1.75rem' }}>
          {(Array.isArray(recs?.tiers) ? recs.tiers : []).map((tier) => {
            const isSelected = selectedTier === tier.tier;
            const isRecommended = tier.tier === 2;
            const isCritical = tier.tier === 1;

            return (
              <div
                key={tier.id}
                onClick={() => setSelectedTier(tier.tier)}
                style={{
                  padding: '1.25rem',
                  borderRadius: '12px',
                  background: isSelected
                    ? 'linear-gradient(135deg, rgba(2, 132, 199, 0.2) 0%, rgba(56, 189, 248, 0.1) 100%)'
                    : 'rgba(255, 255, 255, 0.02)',
                  border: isSelected
                    ? '2px solid #38bdf8'
                    : isRecommended
                    ? '1px solid rgba(56, 189, 248, 0.4)'
                    : '1px solid rgba(255, 255, 255, 0.08)',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  position: 'relative',
                }}
              >
                {isRecommended && (
                  <span
                    style={{
                      position: 'absolute',
                      top: '-10px',
                      right: '12px',
                      background: 'linear-gradient(135deg, #0284c7, #38bdf8)',
                      color: '#fff',
                      fontSize: '0.65rem',
                      fontWeight: 800,
                      padding: '0.15rem 0.5rem',
                      borderRadius: '10px',
                      textTransform: 'uppercase',
                      letterSpacing: '0.5px',
                    }}
                  >
                    Recommended
                  </span>
                )}
                {isCritical && missingCount > 0 && (
                  <span
                    style={{
                      position: 'absolute',
                      top: '-10px',
                      right: '12px',
                      background: '#ef4444',
                      color: '#fff',
                      fontSize: '0.65rem',
                      fontWeight: 800,
                      padding: '0.15rem 0.5rem',
                      borderRadius: '10px',
                      textTransform: 'uppercase',
                    }}
                  >
                    Immediate
                  </span>
                )}

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 800, color: isSelected ? '#38bdf8' : '#94a3b8' }}>
                    TIER {tier.tier}
                  </span>
                  <span
                    style={{
                      fontSize: '0.7rem',
                      fontWeight: 700,
                      color: isCritical ? '#f87171' : isRecommended ? '#38bdf8' : '#a855f7',
                    }}
                  >
                    {tier.priority.split(' ')[0]}
                  </span>
                </div>

                <div style={{ fontSize: '1rem', fontWeight: 700, color: '#f8fafc', marginBottom: '0.5rem', lineHeight: '1.3' }}>
                  {tier.name}
                </div>

                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem', minHeight: '40px' }}>
                  {tier.description}
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '0.75rem', color: '#94a3b8' }}>
                  <div>
                    <span style={{ display: 'block', color: 'var(--text-secondary)' }}>Days</span>
                    <strong style={{ color: '#f8fafc', fontSize: '0.9rem' }}>{tier.trading_days_to_fetch}</strong>
                  </div>
                  <div>
                    <span style={{ display: 'block', color: 'var(--text-secondary)' }}>Volume</span>
                    <strong style={{ color: '#38bdf8', fontSize: '0.9rem' }}>~{tier.estimated_payload_mb} MB</strong>
                  </div>
                  <div>
                    <span style={{ display: 'block', color: 'var(--text-secondary)' }}>Est. Time (c=8)</span>
                    <strong style={{ color: '#4ade80', fontSize: '0.9rem' }}>
                      {tier.estimated_runtime_seconds_c8 >= 60
                        ? `${Math.round(tier.estimated_runtime_seconds_c8 / 60)} min`
                        : `${tier.estimated_runtime_seconds_c8}s`}
                    </strong>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected Tier Deep Dive & CLI Execution Box */}
        {activeTierObj && (
        <div
          style={{
            background: 'rgba(7, 10, 19, 0.6)',
            borderRadius: '12px',
            border: '1px solid rgba(56, 189, 248, 0.25)',
            padding: '1.5rem',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', marginBottom: '1.25rem' }}>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <h3 style={{ fontSize: '1.15rem', fontWeight: 800, color: '#f8fafc', margin: 0 }}>
                  Tier {activeTierObj.tier}: {activeTierObj.name}
                </h3>
                <span style={{ fontSize: '0.75rem', color: '#38bdf8', fontWeight: 600 }}>
                  ({activeTierObj.target_range.start} → {activeTierObj.target_range.end})
                </span>
              </div>
              <p style={{ margin: '0.35rem 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Targeting {activeTierObj.trading_days_to_fetch} sessions &bull; ~{activeTierObj.estimated_payload_mb} MB compressed &bull; Est. runtime ~{Math.round(activeTierObj.estimated_runtime_seconds_c8)}s
              </p>
            </div>

            <button
              onClick={() => handleTriggerTier(activeTierObj)}
              disabled={isTriggering || activeJob !== null}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.65rem 1.25rem',
                borderRadius: '8px',
                background: 'linear-gradient(135deg, #0284c7, #38bdf8)',
                border: 'none',
                color: '#fff',
                fontSize: '0.85rem',
                fontWeight: 700,
                cursor: isTriggering ? 'not-allowed' : 'pointer',
                boxShadow: '0 4px 15px rgba(56, 189, 248, 0.3)',
              }}
            >
              <Play size={15} fill="#fff" />
              <span>Trigger This Tier Now</span>
            </button>
          </div>

          {/* Capabilities Unlocked */}
          <div style={{ marginBottom: '1.25rem' }}>
            <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
              Capabilities & Alpha Signals Unlocked
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '0.5rem' }}>
              {(Array.isArray(activeTierObj?.unlocked_capabilities)
                ? activeTierObj.unlocked_capabilities
                : []
              ).map((cap, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    fontSize: '0.85rem',
                    color: '#e2e8f0',
                  }}
                >
                  <CheckCircle2 size={16} style={{ color: '#22c55e', flexShrink: 0 }} />
                  <span>{cap}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Copyable CLI Commands */}
          <div>
            <div style={{ fontSize: '0.8rem', fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', marginBottom: '0.5rem' }}>
              Direct Terminal CLI Execution (Strict uv syntax)
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
              {(Array.isArray(activeTierObj?.recommended_cli_commands)
                ? activeTierObj.recommended_cli_commands
                : []
              ).map((cmd, idx) => (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    background: '#090d16',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '8px',
                    padding: '0.65rem 1rem',
                    fontFamily: 'monospace',
                    fontSize: '0.85rem',
                    color: '#38bdf8',
                  }}
                >
                  <span>{cmd}</span>
                  <button
                    onClick={() => handleCopy(cmd, `${activeTierObj.tier}-${idx}`)}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      color: copiedIndex === `${activeTierObj.tier}-${idx}` ? '#4ade80' : '#94a3b8',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      fontSize: '0.75rem',
                      padding: '0.2rem 0.5rem',
                      borderRadius: '4px',
                    }}
                  >
                    {copiedIndex === `${activeTierObj.tier}-${idx}` ? (
                      <>
                        <Check size={14} />
                        <span>Copied!</span>
                      </>
                    ) : (
                      <>
                        <Copy size={14} />
                        <span>Copy</span>
                      </>
                    )}
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
        )}
      </div>
    </div>
  );
};
