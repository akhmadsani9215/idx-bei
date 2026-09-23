import React, { useEffect, useRef, useState, useMemo } from 'react';
import { 
  createChart, 
  CandlestickSeries, 
  HistogramSeries, 
  LineSeries,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type SeriesMarker,
  type Time
} from 'lightweight-charts';
import { 
  Search, 
  RotateCw, 
  TrendingUp, 
  Gauge, 
  Building, 
  Zap, 
  Loader2, 
  AlertCircle, 
  FileText, 
  Star,
  Radio,
  Clock,
  AlertTriangle,
} from 'lucide-react';
import type { Company, StreamEvent } from '../types';
import { fetchStockData, fetchStockBlocks, fetchStockTerminal } from '../services/api';
import {
  formatMarketDateLabel,
  isScreenerOlderThanTerminal,
  resolveScreenerAsOf,
} from '../utils/marketAsOf';

interface ChartTabProps {
  companies: Company[];
  screenerLastUpdated?: string | null;
  selectedTicker?: string;
  onSelectTicker?: (ticker: string) => void;
  lastLiveEvent: StreamEvent | null;
  onOpenMemo?: (company: Company) => void;
  isStarred?: (code: string) => boolean;
  onToggleStar?: (company: Company) => void;
}

export const ChartTab: React.FC<ChartTabProps> = ({
  companies,
  screenerLastUpdated = null,
  selectedTicker = 'BBCA',
  onSelectTicker,
  lastLiveEvent,
  onOpenMemo,
  isStarred,
  onToggleStar,
}) => {
  const [tickerInput, setTickerInput] = useState(selectedTicker);
  const [activeTicker, setActiveTicker] = useState(selectedTicker);
  const [stockRecords, setStockRecords] = useState<any[]>([]);
  const [latestData, setLatestData] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Technical indicator overlay toggles
  const [showEma20, setShowEma20] = useState<boolean>(true);
  const [showEma50, setShowEma50] = useState<boolean>(true);
  const [showBollinger, setShowBollinger] = useState<boolean>(false);
  const [showForeignFlow, setShowForeignFlow] = useState<boolean>(true);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  // Synchronize prop changes
  useEffect(() => {
    if (selectedTicker && selectedTicker !== activeTicker) {
      setTickerInput(selectedTicker);
      setActiveTicker(selectedTicker);
    }
  }, [selectedTicker]);

  const company = companies.find((c) => c.code === activeTicker);

  const terminalAsOf = useMemo(
    () => formatMarketDateLabel(latestData?.time ?? latestData?.Date),
    [latestData],
  );

  const screenerAsOf = useMemo(
    () => resolveScreenerAsOf(company?.price_date, screenerLastUpdated),
    [company?.price_date, screenerLastUpdated],
  );

  const screenerLagsTerminal = useMemo(
    () => isScreenerOlderThanTerminal(screenerAsOf, terminalAsOf),
    [screenerAsOf, terminalAsOf],
  );

  const [terminalMeta, setTerminalMeta] = useState<any>(null);

  // Fetch real market data whenever activeTicker changes
  useEffect(() => {
    let isCancelled = false;
    setLoading(true);
    setFetchError(null);
    setTerminalMeta(null);

    Promise.all([
      fetchStockTerminal(activeTicker, 120).catch(() => null),
      fetchStockData(activeTicker).catch((err) => {
        throw err;
      }),
    ])
      .then(([terminal, data]) => {
        if (isCancelled) return;
        const payload = terminal && terminal.records?.length ? terminal : data;
        if (payload && payload.records && payload.records.length > 0) {
          setStockRecords(payload.records);
          setLatestData(payload.latest || payload.records[payload.records.length - 1]);
          setTerminalMeta(terminal);
        } else {
          setFetchError(`No trading records found for ${activeTicker}`);
        }
        setLoading(false);
      })
      .catch((err) => {
        if (!isCancelled) {
          console.error('[ChartTab] Error fetching real stock data:', err);
          setFetchError(err.message || `Failed to fetch data for ${activeTicker}`);
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [activeTicker]);

  // Fetch aggregate market-flow / optional broker-block payload from backend
  const [blockData, setBlockData] = useState<any>(null);

  useEffect(() => {
    let isCancelled = false;
    fetchStockBlocks(activeTicker)
      .then((data) => {
        if (!isCancelled) {
          setBlockData(data);
        }
      })
      .catch((err) => {
        if (!isCancelled) {
          console.warn('[ChartTab] Block data fetch:', err);
          setBlockData(null);
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [activeTicker]);


  // Handle live WebSocket price updates
  useEffect(() => {
    if (!lastLiveEvent || !candleSeriesRef.current) return;
    if (lastLiveEvent.type === 'price_update' && lastLiveEvent.ticker === activeTicker) {
      if (lastLiveEvent.ohlc) {
        candleSeriesRef.current.update({
          time: lastLiveEvent.ohlc.time as Time,
          open: lastLiveEvent.ohlc.open,
          high: lastLiveEvent.ohlc.high,
          low: lastLiveEvent.ohlc.low,
          close: lastLiveEvent.ohlc.close,
        });
      }
      if (lastLiveEvent.price) {
        setLatestData((prev: any) => ({
          ...prev,
          close: lastLiveEvent.price,
          Close: lastLiveEvent.price,
        }));
      }
    }
  }, [lastLiveEvent, activeTicker]);

  // Build / Render chart using REAL records
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || stockRecords.length === 0) return;

    container.innerHTML = '';

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 480,
      layout: {
        background: { color: '#070a13' },
        textColor: '#9ca3af',
      },
      grid: {
        vertLines: { color: 'rgba(255, 255, 255, 0.05)' },
        horzLines: { color: 'rgba(255, 255, 255, 0.05)' },
      },
      crosshair: {
        mode: 1,
      },
      rightPriceScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
      timeScale: {
        borderColor: 'rgba(255, 255, 255, 0.1)',
      },
    });

    chartInstanceRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });
    candleSeriesRef.current = candleSeries;

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    // Transform REAL records
    const candleData: CandlestickData<Time>[] = [];
    const volData: HistogramData<Time>[] = [];

    stockRecords.forEach((r) => {
      const timeStr = (r.time || (r.Date ? String(r.Date).split('T')[0] : '')) as Time;
      const open = Number(r.open ?? r.OpenPrice ?? r.close ?? r.Close ?? 0);
      const high = Number(r.high ?? r.High ?? open);
      const low = Number(r.low ?? r.Low ?? open);
      const close = Number(r.close ?? r.Close ?? open);
      const vol = Number(r.volume ?? r.Volume ?? 0);

      if (timeStr && open > 0 && high > 0 && low > 0 && close > 0) {
        candleData.push({
          time: timeStr,
          open,
          high,
          low,
          close,
        });

        volData.push({
          time: timeStr,
          value: vol,
          color: close >= open ? 'rgba(16, 185, 129, 0.5)' : 'rgba(239, 68, 68, 0.5)',
        });
      }
    });

    candleSeries.setData(candleData);
    volumeSeries.setData(volData);

    // Optional EMA-20 Overlay
    if (showEma20) {
      const ema20Series = chart.addSeries(LineSeries, {
        color: '#f59e0b',
        lineWidth: 2,
        title: 'EMA 20',
      });
      const ema20Points: LineData<Time>[] = [];
      stockRecords.forEach((r) => {
        const timeStr = (r.time || (r.Date ? String(r.Date).split('T')[0] : '')) as Time;
        if (timeStr && r.EMA20 != null && Number(r.EMA20) > 0) {
          ema20Points.push({ time: timeStr, value: Number(r.EMA20) });
        }
      });
      ema20Series.setData(ema20Points);
    }

    // Optional EMA-50 Overlay
    if (showEma50) {
      const ema50Series = chart.addSeries(LineSeries, {
        color: '#a855f7',
        lineWidth: 2,
        title: 'EMA 50',
      });
      const ema50Points: LineData<Time>[] = [];
      stockRecords.forEach((r) => {
        const timeStr = (r.time || (r.Date ? String(r.Date).split('T')[0] : '')) as Time;
        if (timeStr && r.EMA50 != null && Number(r.EMA50) > 0) {
          ema50Points.push({ time: timeStr, value: Number(r.EMA50) });
        }
      });
      ema50Series.setData(ema50Points);
    }

    // Optional Bollinger Bands
    if (showBollinger) {
      const bbUpper = chart.addSeries(LineSeries, {
        color: 'rgba(56, 189, 248, 0.7)',
        lineWidth: 1,
        lineStyle: 2,
        title: 'BB Upper',
      });
      const bbLower = chart.addSeries(LineSeries, {
        color: 'rgba(56, 189, 248, 0.7)',
        lineWidth: 1,
        lineStyle: 2,
        title: 'BB Lower',
      });
      const upperPts: LineData<Time>[] = [];
      const lowerPts: LineData<Time>[] = [];
      stockRecords.forEach((r) => {
        const timeStr = (r.time || (r.Date ? String(r.Date).split('T')[0] : '')) as Time;
        if (timeStr && r.BB_Upper != null && Number(r.BB_Upper) > 0) {
          upperPts.push({ time: timeStr, value: Number(r.BB_Upper) });
        }
        if (timeStr && r.BB_Lower != null && Number(r.BB_Lower) > 0) {
          lowerPts.push({ time: timeStr, value: Number(r.BB_Lower) });
        }
      });
      bbUpper.setData(upperPts);
      bbLower.setData(lowerPts);
    }

    // Optional Foreign Flow Sub-Panel
    if (showForeignFlow) {
      const foreignSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'foreign',
      });
      foreignSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.65, bottom: 0.02 },
      });
      const foreignPts: HistogramData<Time>[] = [];
      stockRecords.forEach((r) => {
        const timeStr = (r.time || (r.Date ? String(r.Date).split('T')[0] : '')) as Time;
        if (timeStr && (r.ForeignBuy != null || r.ForeignSell != null)) {
          const net = Number(r.ForeignBuy || 0) - Number(r.ForeignSell || 0);
          foreignPts.push({
            time: timeStr,
            value: net,
            color: net >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)',
          });
        }
      });
      foreignSeries.setData(foreignPts);
    }

    // Add markers for corporate action or major aggregate flow
    const markers: SeriesMarker<Time>[] = [];
    if (candleData.length >= 10) {
      // Find highest volume day
      let maxVolIndex = 0;
      let maxVol = 0;
      volData.forEach((v, idx) => {
        if (v.value > maxVol) {
          maxVol = v.value;
          maxVolIndex = idx;
        }
      });

      if (maxVol > 0 && candleData[maxVolIndex]) {
        markers.push({
          time: candleData[maxVolIndex].time,
          position: 'aboveBar',
          color: '#3b82f6',
          shape: 'circle',
          text: `Peak Session Vol: ${(maxVol / 1000000).toFixed(1)}M shares`,
        });
      }
    }

    if (markers.length > 0) {
      createSeriesMarkers(candleSeries, markers);
    }

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
  }, [stockRecords, showEma20, showEma50, showBollinger, showForeignFlow]);

  const handleLoadChart = () => {
    const trimmed = tickerInput.trim().toUpperCase();
    if (trimmed) {
      setActiveTicker(trimmed);
      if (onSelectTicker) onSelectTicker(trimmed);
    }
  };

  // Real closing price and daily change
  const currentPrice = latestData?.close ?? latestData?.Close ?? company?.close ?? 0;
  const prevPrice = latestData?.Previous ?? latestData?.previous_price ?? company?.previous_price;
  const dailyChange = prevPrice && currentPrice ? currentPrice - prevPrice : latestData?.Change ?? company?.daily_change ?? 0;
  const changePct = prevPrice && prevPrice > 0 ? (dailyChange / prevPrice) * 100 : 0;

  // Real technical indicators from backend
  const rsi = latestData?.RSI14 != null ? Number(latestData.RSI14).toFixed(1) : 'N/A';
  const rsiStatus = Number(rsi) >= 70 ? 'Overbought' : Number(rsi) <= 30 ? 'Oversold' : 'Neutral';
  const trend = latestData?.TrendRegime ? String(latestData.TrendRegime).replace('_', ' ') : 'NEUTRAL';
  const ema20 = latestData?.EMA20 != null ? Math.round(Number(latestData.EMA20)).toLocaleString() : '-';
  const ema50 = latestData?.EMA50 != null ? Math.round(Number(latestData.EMA50)).toLocaleString() : '-';
  const volRatio = latestData?.VolRatio20 != null ? `${Number(latestData.VolRatio20).toFixed(2)}x` : '-';

  // Real foreign flow from latest record — null stays unavailable (never invent 0).
  const foreignBuyRaw = latestData?.ForeignBuy;
  const foreignSellRaw = latestData?.ForeignSell;
  const foreignBuy =
    foreignBuyRaw == null || foreignBuyRaw === ''
      ? null
      : Number(foreignBuyRaw);
  const foreignSell =
    foreignSellRaw == null || foreignSellRaw === ''
      ? null
      : Number(foreignSellRaw);
  const foreignBuyN = Number.isFinite(foreignBuy as number) ? (foreignBuy as number) : null;
  const foreignSellN = Number.isFinite(foreignSell as number) ? (foreignSell as number) : null;
  const netForeign =
    foreignBuyN != null && foreignSellN != null ? foreignBuyN - foreignSellN : null;

  // Evidence-based Market Condition
  // Foreign flow is aggregate foreign-investor flow — not broker-level attribution.
  const priceNum = Number(currentPrice);
  const roeVal = company?.roe ?? 0;
  const pbvVal = company?.price_bv ?? 0;
  const yieldVal = company?.yield ?? 0;

  const isBearishTrend = trend.includes('BEARISH');
  const isBullishTrend = trend.includes('BULLISH');
  const isForeignOutflow = netForeign != null && netForeign < 0;
  const isForeignInflow = netForeign != null && netForeign > 0;
  const isOverbought = rsiStatus === 'Overbought';
  const isOversold = rsiStatus === 'Oversold';

  let actionVerdict = {
    title: 'WAIT FOR CONFIRMATION',
    badge: 'NEUTRAL',
    bg: 'rgba(148, 163, 184, 0.10)',
    border: '#94a3b8',
    color: '#cbd5e1',
    risk: 'Unclear',
    riskColor: '#cbd5e1',
    explanation:
      'Current technical and flow evidence is mixed. Monitor price, trend, and foreign flow before acting.',
  };

  if (isBearishTrend && isForeignOutflow) {
    actionVerdict = {
      title: 'WEAKNESS / FOREIGN OUTFLOW',
      badge: 'CAUTION',
      bg: 'rgba(239, 68, 68, 0.10)',
      border: '#ef4444',
      color: '#f87171',
      risk: 'Elevated Risk',
      riskColor: '#f87171',
      explanation:
        'The current trend is bearish and foreign flow is negative. This is aggregate flow only — broker attribution is unavailable.',
    };
  } else if (isBullishTrend && isForeignInflow && !isOverbought) {
    actionVerdict = {
      title: 'POSITIVE MOMENTUM',
      badge: 'WATCH',
      bg: 'rgba(16, 185, 129, 0.10)',
      border: '#10b981',
      color: '#34d399',
      risk: 'Moderate',
      riskColor: '#34d399',
      explanation:
        'Trend and foreign flow are currently positive. Confirmation from price structure and volume is still required.',
    };
  } else if (isOversold && isForeignOutflow) {
    actionVerdict = {
      title: 'OVERSOLD — WATCH FOR REVERSAL',
      badge: 'WATCH',
      bg: 'rgba(234, 179, 8, 0.10)',
      border: '#facc15',
      color: '#facc15',
      risk: 'High Volatility',
      riskColor: '#facc15',
      explanation:
        'RSI is in oversold territory, but foreign flow remains negative. Oversold conditions can persist, so reversal confirmation is required.',
    };
  } else if (isForeignInflow && !isOverbought) {
    actionVerdict = {
      title: 'POSITIVE FLOW',
      badge: 'WATCH',
      bg: 'rgba(16, 185, 129, 0.08)',
      border: '#10b981',
      color: '#34d399',
      risk: 'Moderate',
      riskColor: '#34d399',
      explanation:
        'Foreign flow is positive. Monitor for continuation; broker attribution remains unavailable.',
    };
  }
  // Safe Entry Zone & Exit Rules strictly calculated from quant technical indicators (Bollinger Bands, EMA, ATR)
  const dayLow = latestData?.low ?? latestData?.Low;
  const safeEntryLow = latestData?.BB_Lower
    ? Math.round(latestData.BB_Lower)
    : (dayLow != null ? Math.round(Number(dayLow)) : Math.round(priceNum));
  const safeEntryHigh = latestData?.EMA20 ? Math.round(latestData.EMA20) : Math.round(priceNum);
  const profitTarget = latestData?.BB_Upper ? Math.round(latestData.BB_Upper) : Math.round(priceNum);
  const stopLoss = (latestData?.BB_Lower && latestData?.ATR14) 
    ? Math.max(1, Math.round(latestData.BB_Lower - latestData.ATR14))
    : Math.round(Number(dayLow ?? priceNum));

  const targetGainPct = priceNum > 0 ? (((profitTarget - priceNum) / priceNum) * 100).toFixed(1) : '0.0';
  const stopLossPct = priceNum > 0 ? (((stopLoss - priceNum) / priceNum) * 100).toFixed(1) : '0.0';

  // Verified aggregate market-flow data.
  // Individual broker attribution is not inferred when unavailable.
  const brokerBlocksAvailable = blockData?.broker_blocks_available === true;

  const marketFlow = useMemo(() => {
    const n = (v: unknown): number | null => {
      if (v == null || v === '') return null;
      const x = Number(v);
      return Number.isFinite(x) ? x : null;
    };
    return {
      turnoverRp: n(blockData?.total_turnover_rp),
      regularVolume: n(blockData?.regular_volume_shares),
      vwap: n(blockData?.vwap_price),
      nonRegularValueRp: n(blockData?.non_regular_value_rp),
      nonRegularVolume: n(blockData?.non_regular_volume_shares),
      nonRegularFrequency: n(blockData?.non_regular_frequency),
      foreignBuy: n(blockData?.foreign_buy_shares),
      foreignSell: n(blockData?.foreign_sell_shares),
      netForeignRp: n(blockData?.net_foreign_flow_rp),
      available: blockData != null,
    };
  }, [blockData]);

  const fmtSharesM = (v: number | null) =>
    v == null ? '—' : `${(v / 1e6).toFixed(2)}M shares`;
  const fmtRpB = (v: number | null) =>
    v == null ? '—' : `Rp ${(v / 1e9).toFixed(2)}B`;
  const fmtCount = (v: number | null) =>
    v == null ? '—' : v.toLocaleString();
  return (
    <div className="tab-panel active">
      {/* Search & Stock Header */}
      <div className="glass-card" style={{ marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <label style={{ fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <Search size={16} /> Stock Ticker:
            </label>
            <input
              type="text"
              className="form-control"
              style={{ width: '130px', textTransform: 'uppercase', fontWeight: 700 }}
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && handleLoadChart()}
              placeholder="e.g. BBCA"
            />
            <button
              className="nav-btn active"
              style={{ padding: '0.6rem 1.2rem', cursor: 'pointer' }}
              onClick={handleLoadChart}
            >
              {loading ? (
                <Loader2 size={14} className="spin" style={{ marginRight: '0.4rem' }} />
              ) : (
                <RotateCw size={14} style={{ marginRight: '0.4rem' }} />
              )}
              Load Real Data
            </button>
          </div>

          <div style={{ display: 'flex', gap: '1rem', fontSize: '0.95rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, color: '#fff' }}>
              {company?.name || `${activeTicker} Tbk`}
            </span>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
              <span style={{ color: dailyChange >= 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontWeight: 700, fontFamily: 'monospace', fontSize: '1.25rem' }}>
                Rp {Number(currentPrice).toLocaleString()}
              </span>
              {prevPrice != null && (
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: dailyChange >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  {dailyChange >= 0 ? '+' : ''}{dailyChange.toLocaleString()} ({changePct.toFixed(2)}%)
                </span>
              )}
            </div>

            {/* Quick Actions: Star & Memo */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginLeft: '0.5rem' }}>
              {onToggleStar && company && (
                <button
                  onClick={() => onToggleStar(company)}
                  style={{
                    background: isStarred && isStarred(activeTicker) ? 'rgba(250, 204, 21, 0.2)' : 'rgba(255, 255, 255, 0.05)',
                    border: `1px solid ${isStarred && isStarred(activeTicker) ? '#facc15' : 'rgba(255, 255, 255, 0.15)'}`,
                    color: isStarred && isStarred(activeTicker) ? '#facc15' : '#9ca3af',
                    padding: '0.45rem 0.75rem',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                  }}
                  title="Toggle Watchlist"
                >
                  <Star size={14} fill={isStarred && isStarred(activeTicker) ? '#facc15' : 'none'} />
                  <span>{isStarred && isStarred(activeTicker) ? 'Watched' : 'Watch'}</span>
                </button>
              )}

              {onOpenMemo && company && (
                <button
                  onClick={() => onOpenMemo(company)}
                  style={{
                    background: 'rgba(56, 189, 248, 0.15)',
                    border: '1px solid rgba(56, 189, 248, 0.3)',
                    color: '#38bdf8',
                    padding: '0.45rem 0.75rem',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '4px',
                    fontSize: '0.8rem',
                    fontWeight: 700,
                  }}
                  title="Print / Save 1-Page Investment Memo"
                >
                  <FileText size={14} />
                  <span>1-Page Memo</span>
                </button>
              )}
            </div>
          </div>
        </div>

        {(terminalAsOf || screenerAsOf) && (
          <div
            style={{
              marginTop: '0.85rem',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '0.75rem 1.25rem',
              fontSize: '0.8rem',
              color: 'var(--text-secondary)',
              alignItems: 'center',
            }}
          >
            {terminalAsOf && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                <Clock size={14} style={{ color: '#38bdf8' }} />
                <span>
                  Market data as-of (data date):{' '}
                  <strong style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{terminalAsOf}</strong>
                </span>
              </span>
            )}
            {screenerAsOf && (
              <span>
                Screener overlay as-of (data date):{' '}
                <strong style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{screenerAsOf}</strong>
              </span>
            )}
            {terminalMeta?.data_quality && (
              <span>
                DQ {terminalMeta.data_quality}
                {terminalMeta.source ? ` · ${terminalMeta.source}` : ''}
              </span>
            )}
          </div>
        )}

        <div
          style={{
            marginTop: '0.75rem',
            display: 'grid',
            gap: '0.5rem',
            fontSize: '0.8rem',
            color: '#fde68a',
          }}
        >
          <div>
            ORDERBOOK:{' '}
            {terminalMeta?.orderbook?.status
              ? `ORDERBOOK ${terminalMeta.orderbook.status}`
              : 'ORDERBOOK UNAVAILABLE'}
          </div>
          <div>
            TAPE:{' '}
            {terminalMeta?.tape?.status
              ? `TRANSACTION TAPE ${terminalMeta.tape.status}`
              : 'TRANSACTION TAPE UNAVAILABLE'}
          </div>
          <div style={{ color: '#94a3b8' }}>
            Broker scope: MARKET-WIDE only — not stock-specific attribution.
          </div>
          {terminalMeta?.screener?.close_pressure?.why_signal && (
            <div style={{ color: '#cbd5e1' }}>
              Engine: {terminalMeta.screener.close_pressure.setup || '—'} ·{' '}
              {terminalMeta.screener.close_pressure.why_signal}
            </div>
          )}
        </div>

        {screenerLagsTerminal && terminalAsOf && screenerAsOf && (
          <div
            style={{
              marginTop: '0.75rem',
              background: 'rgba(234, 179, 8, 0.1)',
              border: '1px solid rgba(234, 179, 8, 0.35)',
              borderRadius: '10px',
              padding: '0.75rem 1rem',
              color: '#fbbf24',
              fontSize: '0.82rem',
              fontWeight: 600,
              display: 'flex',
              alignItems: 'flex-start',
              gap: '0.5rem',
            }}
          >
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '1px' }} />
            <span>
              Screener data is older than the latest market data shown on this terminal.
              {' '}Screener as-of <strong style={{ fontFamily: 'monospace' }}>{screenerAsOf}</strong>
              {' · '}Terminal as-of <strong style={{ fontFamily: 'monospace' }}>{terminalAsOf}</strong>.
            </span>
          </div>
        )}
      </div>

      {/* Newbie Action Box (Actionable Wealth Decision Engine) */}
      <div style={{
        background: actionVerdict.bg,
        border: `1px solid ${actionVerdict.border}`,
        borderRadius: '16px',
        padding: '1.25rem 1.5rem',
        marginBottom: '1.5rem',
        boxShadow: `0 8px 30px ${actionVerdict.border}15`,
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
        gap: '1.25rem',
        alignItems: 'center',
      }}>
        {/* 1. Primary Plain-English Verdict */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem' }}>
            <span style={{
              padding: '0.2rem 0.6rem',
              borderRadius: '6px',
              fontSize: '0.72rem',
              fontWeight: 800,
              background: actionVerdict.border,
              color: '#000000',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}>
              {actionVerdict.badge}
            </span>
            <span style={{ fontSize: '0.75rem', color: actionVerdict.riskColor, fontWeight: 700 }}>
              • {actionVerdict.risk}
            </span>
          </div>
          <h3 style={{ margin: '0 0 0.35rem', fontSize: '1.15rem', fontWeight: 800, color: '#f8fafc' }}>
            {actionVerdict.title}
          </h3>
          <p style={{ margin: 0, fontSize: '0.82rem', color: '#cbd5e1', lineHeight: 1.4 }}>
            {actionVerdict.explanation}
          </p>
        </div>

        {/* 2. Safe Entry & Targets */}
        <div style={{
          background: 'rgba(15, 23, 42, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '12px',
          padding: '0.85rem 1rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.4rem',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Technical Entry Range:</span>
            <strong style={{ color: '#38bdf8' }}>
              Rp {safeEntryLow.toLocaleString()} – Rp {safeEntryHigh.toLocaleString()}
            </strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Upper Technical Target ({Number(targetGainPct) >= 0 ? `+${targetGainPct}%` : `${targetGainPct}%`}):</span>
            <strong style={{ color: '#10b981' }}>
              Rp {profitTarget.toLocaleString()}
            </strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Technical Invalidation Level ({Number(stopLossPct) >= 0 ? `+${stopLossPct}%` : `${stopLossPct}%`}):</span>
            <strong style={{ color: '#ef4444' }}>
              Rp {stopLoss.toLocaleString()}
            </strong>
          </div>
        </div>

        {/* 3. Foreign Flow & Fundamentals */}
        <div style={{
          background: 'rgba(15, 23, 42, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '12px',
          padding: '0.85rem 1rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.4rem',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Foreign Flow:</span>
            <strong
              style={{
                color:
                  netForeign == null
                    ? '#94a3b8'
                    : netForeign >= 0
                      ? '#10b981'
                      : '#ef4444',
              }}
            >
              {netForeign == null || !Number.isFinite(priceNum) || priceNum <= 0
                ? '—'
                : netForeign >= 0
                  ? `+Rp ${((netForeign * priceNum) / 1e9).toFixed(1)}B Inflow`
                  : `-Rp ${((Math.abs(netForeign) * priceNum) / 1e9).toFixed(1)}B Outflow`}
            </strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>ROE & PBV:</span>
            <strong style={{ color: '#f8fafc' }}>
              {roeVal ? `${roeVal}%` : '—'} / {pbvVal ? `${pbvVal}x` : '—'}
            </strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem' }}>
            <span style={{ color: 'var(--text-secondary)' }}>Dividend Yield:</span>
            <strong style={{ color: yieldVal >= 4.0 ? '#facc15' : '#94a3b8' }}>
              {yieldVal ? `${yieldVal.toFixed(1)}%` : '—'}
            </strong>
          </div>
        </div>
      </div>

      {/* Chart Canvas */}
      <div className="glass-card" style={{ padding: '1.5rem', marginBottom: '1.5rem', position: 'relative' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
          <h3 style={{ fontSize: '1.1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
            <TrendingUp size={18} style={{ color: 'var(--accent-blue)' }} /> Real Historical Candlestick & Volume
          </h3>
          
          {/* Indicator Toggles */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
            <button
              onClick={() => setShowEma20(!showEma20)}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                background: showEma20 ? 'rgba(245, 158, 11, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                color: showEma20 ? '#fbbf24' : '#9ca3af',
              }}
            >
              EMA-20
            </button>
            <button
              onClick={() => setShowEma50(!showEma50)}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                border: '1px solid rgba(168, 85, 247, 0.4)',
                background: showEma50 ? 'rgba(168, 85, 247, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                color: showEma50 ? '#c084fc' : '#9ca3af',
              }}
            >
              EMA-50
            </button>
            <button
              onClick={() => setShowBollinger(!showBollinger)}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                border: '1px solid rgba(56, 189, 248, 0.4)',
                background: showBollinger ? 'rgba(56, 189, 248, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                color: showBollinger ? '#38bdf8' : '#9ca3af',
              }}
            >
              Bollinger
            </button>
            <button
              onClick={() => setShowForeignFlow(!showForeignFlow)}
              style={{
                padding: '0.3rem 0.65rem',
                borderRadius: '6px',
                fontSize: '0.75rem',
                fontWeight: 600,
                cursor: 'pointer',
                border: '1px solid rgba(16, 185, 129, 0.4)',
                background: showForeignFlow ? 'rgba(16, 185, 129, 0.2)' : 'rgba(255, 255, 255, 0.03)',
                color: showForeignFlow ? '#34d399' : '#9ca3af',
              }}
            >
              Net Foreign Flow
            </button>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.3rem', marginLeft: '0.5rem' }}>
              <Zap size={14} style={{ color: 'var(--accent-gold)' }} /> {stockRecords.length} sessions
            </span>
          </div>
        </div>

        {loading && (
          <div style={{ height: '480px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem', color: 'var(--text-secondary)' }}>
            <Loader2 size={36} className="spin" style={{ color: 'var(--accent-blue)' }} />
            <p>Loading verified historical exchange records for {activeTicker}...</p>
          </div>
        )}

        {fetchError && !loading && (
          <div style={{ height: '480px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem', color: 'var(--accent-red)' }}>
            <AlertCircle size={36} />
            <p>{fetchError}</p>
          </div>
        )}

        <div
          ref={chartContainerRef}
          id="tvChartContainer"
          style={{
            width: '100%',
            height: '480px',
            position: 'relative',
            borderRadius: '12px',
            overflow: 'hidden',
            background: '#070a13',
            border: '1px solid var(--panel-border)',
            display: loading || fetchError ? 'none' : 'block',
          }}
        />
      </div>

      {/* Real Technical Summary & Foreign Flow Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '1.5rem' }}>
        <div className="glass-card">
          <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Gauge size={18} style={{ color: 'var(--accent-green)' }} /> Real Vectorized Technical Indicators
          </h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.8rem' }}>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>RSI (14)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent-blue)' }}>
                {rsi} <span style={{ fontSize: '0.8rem', fontWeight: 500 }}>({rsiStatus})</span>
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Trend Regime</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: trend.includes('BULLISH') ? 'var(--accent-green)' : trend.includes('BEARISH') ? 'var(--accent-red)' : '#fff' }}>
                {trend}
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>EMA-20 / EMA-50</div>
              <div style={{ fontSize: '1rem', fontWeight: 600, color: '#fff' }}>
                {ema20} / {ema50}
              </div>
            </div>
            <div style={{ background: 'rgba(255,255,255,0.03)', padding: '0.75rem', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>20-Day Volume Ratio</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent-orange)' }}>
                {volRatio}
              </div>
            </div>
          </div>
        </div>

        <div className="glass-card">
          <h3 style={{ fontSize: '1.1rem', marginBottom: '1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Building size={18} style={{ color: 'var(--accent-purple)' }} /> Foreign Flow Footprint
          </h3>
          <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.8 }}>
            <div>
              <strong style={{ color: '#fff' }}>Foreign Buy:</strong>{' '}
              <span className="numeric" style={{ color: 'var(--accent-green)' }}>
                {foreignBuyN == null ? '—' : `${(foreignBuyN / 1000000).toFixed(2)}M shares`}
              </span>
            </div>
            <div>
              <strong style={{ color: '#fff' }}>Foreign Sell:</strong>{' '}
              <span className="numeric" style={{ color: 'var(--accent-red)' }}>
                {foreignSellN == null ? '—' : `${(foreignSellN / 1000000).toFixed(2)}M shares`}
              </span>
            </div>
            <div style={{ marginTop: '0.5rem', paddingTop: '0.5rem', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <strong style={{ color: '#fff' }}>Net Foreign Flow:</strong>{' '}
              <span
                className="numeric"
                style={{
                  fontWeight: 700,
                  fontSize: '1.05rem',
                  color:
                    netForeign == null
                      ? '#94a3b8'
                      : netForeign >= 0
                        ? 'var(--accent-green)'
                        : 'var(--accent-red)',
                }}
              >
                {netForeign == null
                  ? '—'
                  : `${netForeign >= 0 ? '+' : ''}${(netForeign / 1000000).toFixed(2)}M shares (${
                      netForeign >= 0 ? 'Foreign Inflow' : 'Foreign Outflow'
                    })`}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Verified Aggregate Market Flow Panel */}
      <div className="glass-card" style={{
        padding: '1.5rem',
        marginTop: '1.5rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '1.25rem',
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
          borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
          paddingBottom: '1rem',
        }}>
          <div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              marginBottom: '0.25rem',
            }}>
              <Radio size={22} style={{ color: '#38bdf8' }} />
              <h3 style={{
                margin: 0,
                fontSize: '1.2rem',
                fontWeight: 800,
                color: '#f8fafc',
              }}>
                Verified Market Flow
              </h3>
              <span style={{
                padding: '0.2rem 0.6rem',
                borderRadius: '12px',
                background: brokerBlocksAvailable
                  ? 'rgba(16, 185, 129, 0.15)'
                  : 'rgba(234, 179, 8, 0.15)',
                border: brokerBlocksAvailable
                  ? '1px solid rgba(16, 185, 129, 0.35)'
                  : '1px solid rgba(234, 179, 8, 0.35)',
                color: brokerBlocksAvailable ? '#34d399' : '#facc15',
                fontSize: '0.72rem',
                fontWeight: 800,
                letterSpacing: '0.5px',
              }}>
                {brokerBlocksAvailable ? 'BROKER DETAIL AVAILABLE' : 'BROKER ATTRIBUTION UNAVAILABLE'}
              </span>
            </div>

            <p style={{
              margin: 0,
              fontSize: '0.85rem',
              color: '#94a3b8',
              maxWidth: '850px',
            }}>
              Verified aggregate market-flow data for {activeTicker}.
              Individual buyer/seller broker attribution is not inferred when
              transaction-level broker data is unavailable.
            </p>
          </div>
        </div>

        {/* Aggregate Market KPIs */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: '1rem',
        }}>
          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Total Turnover
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#f8fafc',
            }}>
              {fmtRpB(marketFlow.turnoverRp)}
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              VWAP
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#38bdf8',
            }}>
              {marketFlow.vwap != null && marketFlow.vwap > 0
                ? `Rp ${marketFlow.vwap.toLocaleString()}`
                : '—'}
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Non-Regular Value
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#facc15',
            }}>
              {fmtRpB(marketFlow.nonRegularValueRp)}
            </div>
            <div style={{
              fontSize: '0.7rem',
              color: '#94a3b8',
              marginTop: '0.2rem',
            }}>
              {fmtCount(marketFlow.nonRegularFrequency)} frequency
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Regular Volume
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#f8fafc',
            }}>
              {fmtSharesM(marketFlow.regularVolume)}
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Foreign Buy
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#34d399',
            }}>
              {fmtSharesM(marketFlow.foreignBuy)}
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Foreign Sell
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color: '#f87171',
            }}>
              {fmtSharesM(marketFlow.foreignSell)}
            </div>
          </div>

          <div style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '10px',
            padding: '0.85rem 1rem',
          }}>
            <div style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '0.2rem',
            }}>
              Net Foreign Flow
            </div>
            <div style={{
              fontSize: '1.2rem',
              fontWeight: 800,
              color:
                marketFlow.netForeignRp == null
                  ? '#94a3b8'
                  : marketFlow.netForeignRp >= 0
                    ? '#34d399'
                    : '#f87171',
            }}>
              {fmtRpB(marketFlow.netForeignRp)}
            </div>
          </div>
        </div>

        {!brokerBlocksAvailable && (
          <div style={{
            padding: '0.8rem 1rem',
            borderRadius: '8px',
            background: 'rgba(234, 179, 8, 0.07)',
            border: '1px solid rgba(234, 179, 8, 0.18)',
            color: '#cbd5e1',
            fontSize: '0.75rem',
            lineHeight: 1.5,
          }}>
            Broker-level transaction tape tidak tersedia untuk sesi ini.
            Dashboard tidak mengarang buyer/seller broker, whale classification,
            atau smart-accumulation ratio. Hanya aggregate market flow yang
            ditampilkan.
          </div>
        )}

        <div style={{
          padding: '0.8rem 1rem',
          borderRadius: '8px',
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid rgba(255,255,255,0.05)',
          fontSize: '0.75rem',
          color: '#94a3b8',
        }}>
          Non-regular volume:{' '}
          {marketFlow.nonRegularVolume == null
            ? '—'
            : `${marketFlow.nonRegularVolume.toLocaleString()} shares`}
          {' · '}
          Non-regular frequency: {fmtCount(marketFlow.nonRegularFrequency)}
          {' · '}
          Broker transaction tape: {brokerBlocksAvailable ? 'available' : 'not available'}
        </div>
      </div>
    </div>
  );
};
