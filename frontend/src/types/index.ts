export type TabType =
  | 'opportunities'
  | 'terminal'
  | 'power_map'
  | 'big_money'
  | 'simulator'
  | 'trading_plan'
  | 'ingestion';

export interface DatasetTimeseriesMeta {
  total_dates: number;
  start_date: string | null;
  end_date: string | null;
  daily_partitions_count: number;
  compacted_partitions_count: number;
  total_size_mb: number;
}

export interface ParquetExportMeta {
  exists: boolean;
  row_count: number;
  size_mb: number;
  modified_iso: string | null;
}

export interface IngestionInventory {
  timeseries: Record<string, DatasetTimeseriesMeta>;
  parquet_exports: Record<string, ParquetExportMeta>;
  fundamental_snapshots: {
    total_listed_companies: number;
    detailed_profiles_scraped: number;
    profile_coverage_pct: number;
    financial_ratios: { exists: boolean; size_mb: number; modified_iso: string | null };
    corporate_actions: { exists: boolean; size_mb: number; modified_iso: string | null };
    broker_directory: { exists: boolean; size_mb: number; modified_iso: string | null };
  };
  ksei_drift: {
    files_count: number;
    files: Array<{ file: string; size_mb: number; modified_iso: string | null }>;
  };
  system: {
    usd_idr: {
      rate: number | null;
      last_updated: string | null;
      status?: string;
      source?: string;
      quality?: string;
      confidence?: number | null;
      is_live?: boolean;
      is_market_quote?: boolean;
      is_default_constant?: boolean;
      is_verified_fx?: boolean;
      notes?: string;
    };
  };
}

export interface CalendarGapInfo {
  dataset: string;
  start_date: string;
  end_date: string;
  total_calendar_weekdays: number;
  ingested_days: number;
  official_holidays_count: number;
  official_holidays: Array<{ date: string; holiday_name: string }>;
  true_missing_trading_days_count: number;
  true_missing_trading_days: string[];
  coverage_percentage: number;
}

export interface BackfillTier {
  tier: number;
  id: string;
  name: string;
  priority: string;
  description: string;
  target_range: { start: string; end: string };
  trading_days_to_fetch: number;
  estimated_payload_mb: number;
  estimated_runtime_seconds_c8: number;
  unlocked_capabilities: string[];
  recommended_cli_commands: string[];
}

export interface BackfillRecommendations {
  as_of_date: string;
  summary: {
    current_status: string;
    immediate_gaps_count: number;
    immediate_gaps: string[];
    recommended_action: string;
  };
  tiers: BackfillTier[];
}

export type FreshnessStatus =
  | 'current'
  | 'screener_stale'
  | 'screener_missing'
  | 'unknown';

export interface FreshnessContract {
  last_successful_ingestion: {
    available: boolean;
    job_id: string | null;
    job_type: string | null;
    completed_at: string | null;
    source: string | null;
    note: string | null;
  };
  market_data: {
    as_of_date: string | null;
    partitions: Record<
      string,
      {
        end_date: string | null;
        start_date: string | null;
        total_dates: number;
      }
    >;
    parquet_modified_iso: Record<string, string | null>;
  };
  screener_snapshot: {
    file: string;
    exists: boolean;
    modified_iso: string | null;
    content_last_updated: string | null;
  };
  status: FreshnessStatus;
  screener_lagging: boolean;
  warning: string | null;
  comparison_basis: string | null;
  ingestion_evidence_at: string | null;
  ingestion_evidence_source: string | null;
}

export interface IngestionStatusResponse {
  status: 'healthy' | 'warning' | 'critical';
  health_score: number;
  inventory: IngestionInventory;
  gaps: CalendarGapInfo;
  recommendations: BackfillRecommendations;
  freshness?: FreshnessContract;
  orchestration?: OrchestrationStatus;
  generated_at: string;
}

export type PipelineRunStatus =
  | 'SUCCESS'
  | 'PARTIAL'
  | 'FAILED'
  | 'UNAVAILABLE'
  | 'IDLE'
  | 'PENDING'
  | 'RUNNING';

export interface OrchestrationPipeline {
  id: string;
  label: string;
  availability: 'AVAILABLE' | 'PARTIAL' | 'UNAVAILABLE';
  status: PipelineRunStatus | string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_sec?: number | null;
  records?: number | null;
  source?: string | null;
  quality?: string | number | null;
  warnings?: string[];
  errors?: string[];
  notes?: string | null;
}

export interface OrchestrationStatus {
  integrations: {
    realtime?: string;
    ai?: string;
    telegram?: string;
    payment?: string;
  };
  pipelines: OrchestrationPipeline[];
  last_sync_all?: {
    overall_status?: string;
    started_at?: string | null;
    completed_at?: string | null;
    duration_sec?: number | null;
    pipelines?: OrchestrationPipeline[];
  } | null;
}

export interface ScoreBreakdown {
  financial: number;
  valuation: number;
  network: number;
  total: number;
}

export interface BoardMember {
  name: string;
  role?: string;
  title?: string;
  is_shared?: boolean;
}

export interface Shareholder {
  name: string;
  percentage: number;
  is_controller?: boolean;
  is_super_insider?: boolean;
}

export interface Subsidiary {
  name: string;
  percentage: number;
  bidang_usaha?: string;
}

export interface Company {
  code: string;
  name: string;
  sector: string;
  sub_sector?: string;
  industry?: string;
  sub_industry?: string;
  roe?: number | null;
  roa?: number | null;
  npm?: number | null;
  de_ratio?: number | null;
  per?: number | null;
  /** Canonical price-to-book from screener producer. */
  price_bv?: number | null;
  /** Legacy alias of `price_bv`. */
  pbv?: number | null;
  /** Legacy alias of `close`. Prefer `close`. */
  price?: number | null;
  /** Canonical last close from screener producer. */
  close?: number | null;
  daily_change?: number | null;
  daily_change_pct?: number | null;
  previous_price?: number | null;
  /** Market/data date for screener price fields (not browser clock). */
  price_date?: string | null;
  dps?: number | null;
  yield?: number | null;
  score: ScoreBreakdown;
  board_members?: BoardMember[];
  directors?: BoardMember[];
  commissioners?: BoardMember[];
  shareholders?: Shareholder[];
  subsidiaries?: Subsidiary[];
  shared_directors?: any[];
  /** Canonical market-cap field from screener producer (Rp bn estimate). */
  estimated_mcap?: number | null;
  /** Legacy alias — prefer `estimated_mcap`. */
  market_cap?: number | null;
  is_blue_chip?: boolean;
  conglomerate?: string | null;
}

export interface InsiderHolding {
  code: string;
  percentage: number;
  value?: number;
  value_idr?: number;
  is_controller?: boolean;
}

export interface ConnectedRole {
  code: string;
  role: string;
  title: string;
}

export interface SuperInsider {
  name: string;
  clean_name?: string;
  total_value?: number;
  total_value_idr?: number;
  holdings?: InsiderHolding[];
  portfolio?: InsiderHolding[];
  holding_count?: number;
  connected_roles?: ConnectedRole[];
}

export interface Conglomerate {
  controller_name?: string;
  name?: string;
  companies: string[];
  total_assets?: number;
  total_market_cap?: number;
  average_roe?: number;
  median_roe?: number;
  average_pbv?: number;
  dominant_sector?: string;
}

export interface DashboardData {
  companies: Company[];
  super_insiders: SuperInsider[];
  conglomerates: Conglomerate[];
  /** Screener snapshot generation timestamp from network_alpha_data.json (data age, not live). */
  last_updated?: string | null;
}

export interface StreamEvent {
  type: string;
  ticker?: string;
  price?: number;
  change?: number;
  score?: number;
  ohlc?: {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
  };
  status?: string;
  data?: any;
}

export interface BacktestParams {
  strategy: 'foreign_flow' | 'bandarmology' | 'stealth_accumulation' | 'sharia_value' | 'composite_alpha' | 'dividend_arbitrage';
  holding_days: number;
  top_n: number;
  min_turnover_rp: number;
  start_date?: string;
  end_date?: string;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  position_sizing?: 'equal_weight' | 'volatility_parity';
}

export interface BacktestMetrics {
  total_return_pct: number;
  /** Always null/unavailable — never treat as CAGR or mirror of total_return_pct. */
  cagr_pct?: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number | null;
  win_rate_pct: number | null;
  profit_factor?: number | null;
  total_trades: number;
  /** Number of trade rows included in the API payload (may be truncated). */
  trades_returned?: number;
  avg_trade_return_pct: number | null;
  /** Null when no benchmark series was provided to the engine. */
  benchmark_return_pct: number | null;
  /** Null when no benchmark series was provided to the engine. */
  alpha_pct: number | null;
  strategy?: string;
  holding_days?: number;
  position_sizing?: string;
  total_events?: number;
  strategy_a_naive_hold?: BacktestMetrics;
  strategy_b_precum_exit?: BacktestMetrics;
  strategy_c_postex_rebuy?: BacktestMetrics;
}

export interface EquityPoint {
  time: string;
  value: number;
}

export interface BacktestTrade {
  EntryDate: string;
  ExitDate: string;
  StockCode: string;
  EntryPrice: number;
  ExitPrice: number;
  ReturnPct: number;
  Return: number;
  Weight?: number;
  WeightedReturn?: number;
}

export interface BacktestResponse {
  metrics: BacktestMetrics;
  equity_curve: EquityPoint[];
  trades: BacktestTrade[];
}

export interface StealthAnomaly {
  StockCode: string;
  PriceChangePct: number;
  CumPriceChangePct?: number;
  SmartMoneyDelta: number;
  NetForeignFlowRpB?: number;
  CumNetForeignFlowRpB?: number;
  TurnoverRpB?: number;
  FlowRatioPct?: number;
  AccumulationScore?: number;
  WyckoffPhase?: string;
  Signal: 'STEALTH_ACCUMULATION' | 'MARKUP_CONFIRMATION' | 'RETAIL_TRAP' | 'DISTRIBUTION' | string;
  Priority?: 'HIGH' | 'MEDIUM' | 'LOW' | string;
}

export interface StealthAccumulationSummary {
  on_date: string | null;
  smart_money_turnover_rp_b?: number | null;
  retail_turnover_rp_b?: number | null;
  smart_money_delta: number | null;
  market_signal: string;
  anomalies_detected: number;
  broker_attribution_available: boolean;
}

export interface StealthAccumulationResponse {
  summary: StealthAccumulationSummary | string;
  signal: string;
  smart_money_delta: number | null;
  anomalies: StealthAnomaly[];
}

export interface DividendOpportunity {
  StockCode: string;
  StockName?: string;
  Price?: number;
  DPS: number;
  DividendYield: number;
  CumDate: string;
  ExDate: string;
  PaymentDate?: string;
  PayoutRatio?: number;
  TrapScore?: number;
  Recommendation?: string;
}

export interface DividendAnalysis {
  ticker: string;
  has_dividend: boolean;
  message?: string;
  dividend?: {
    dps: number;
    yield_pct: number;
    cum_date: string;
    ex_date: string;
    payment_date: string;
  };
  metrics?: {
    payout_ratio: number;
    cash_coverage: number;
    fcf_yield: number;
    earnings_growth_yoy: number;
  };
  trap_score?: number;
  trap_level?: 'LOW' | 'MODERATE' | 'HIGH' | 'CRITICAL';
  recommendation?: 'BUY' | 'HOLD' | 'AVOID' | 'ARBITRAGE';
  playbook?: {
    strategy_a_naive_hold_return?: number;
    strategy_b_pre_cum_exit_return?: number;
    strategy_c_post_ex_rebuy_return?: number;
    best_strategy?: string;
  };
  risk_breakdown?: {
    payout_risk: number;
    cash_flow_risk: number;
    cyclicality_risk: number;
    leverage_risk: number;
  };
}

export interface WatchlistItem {
  code: string;
  name: string;
  sector?: string;
  price?: number;
  close?: number;
  daily_change?: number;
  daily_change_pct?: number;
  score?: number;
  addedAt: string;
}

export interface LiveAlert {
  id: string;
  ticker: string;
  type: 'STEALTH_ACCUMULATION' | 'RETAIL_TRAP' | 'DIVIDEND_CUM' | 'PASAR_NEGO';
  title: string;
  message: string;
  timestamp: string;
}

export type ScreenerTimeframe = 'close_pressure' | 'swing' | 'long_term';

export interface ScreenerResult {
  ticker: string;
  company?: string | null;
  price?: number | null;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  value?: number | null;
  setup?: string | null;
  signal?: string | null;
  engine_score?: number | null;
  trend?: string | null;
  pressure?: number | null;
  foreign?: number | null;
  liquidity?: number | null;
  lifecycle?: string | null;
  timeframe?: ScreenerTimeframe | string | null;
  entry_zone?: number | null;
  tp1?: number | null;
  tp2?: number | null;
  tp3?: number | null;
  cl1?: number | null;
  cl2?: number | null;
  cl3?: number | null;
  rr1?: number | null;
  rr2?: number | null;
  rr3?: number | null;
  historical_tp_probability?: number | null;
  median_days?: number | null;
  mfe?: number | null;
  mae?: number | null;
  sample_size?: number | null;
  stats_status?: string | null;
  stats_note?: string | null;
  data_quality?: string | null;
  source?: string | null;
  as_of?: string | null;
  confidence?: number | null;
  why_signal?: string | null;
  status?: string | null;
  engine_version?: string | null;
}

export interface ScreenerResponse {
  results: ScreenerResult[];
  meta: {
    status?: string;
    timeframe?: string;
    as_of?: string | null;
    count?: number;
    total_matched?: number;
    limit?: number;
    cursor?: number;
    next_cursor?: number | null;
    engine_version?: string;
    limitations?: string[];
    [key: string]: unknown;
  };
}
