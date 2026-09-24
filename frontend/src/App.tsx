import React, { useState, useEffect, Suspense, lazy } from 'react';
import { Header } from './components/Header';
import { ScreenerTab } from './components/ScreenerTab';
import { BigMoneyTab } from './components/BigMoneyTab';
import { TradingPlanTab } from './components/TradingPlanTab';
import { useDashboardData } from './hooks/useDashboardData';
import { useLiveStream } from './hooks/useLiveStream';
import { useWatchlist } from './hooks/useWatchlist';
import { AlertTriangle, Loader2 } from 'lucide-react';
import type { TabType, Company, LiveAlert } from './types';

// Code-split heavy sub-panels and visualization graphs
const ChartTab = lazy(() => import('./components/ChartTab').then(m => ({ default: m.ChartTab })));
const PowerMapTab = lazy(() => import('./components/PowerMapTab').then(m => ({ default: m.PowerMapTab })));
const BacktesterTab = lazy(() => import('./components/BacktesterTab').then(m => ({ default: m.BacktesterTab })));
const IngestionTab = lazy(() => import('./components/IngestionTab').then(m => ({ default: m.IngestionTab })));
const InvestorMemoModal = lazy(() => import('./components/InvestorMemoModal').then(m => ({ default: m.InvestorMemoModal })));
const WatchlistDrawer = lazy(() => import('./components/WatchlistDrawer').then(m => ({ default: m.WatchlistDrawer })));

const TabFallback: React.FC = () => (
  <div style={{
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '420px',
    gap: '1rem',
    color: 'var(--text-secondary)',
  }}>
    <Loader2 size={36} className="spinning" style={{ color: '#38bdf8' }} />
    <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>Loading quantitative view...</span>
  </div>
);

function parseRouteFromUrl(): { tab: TabType; ticker: string } {
  if (typeof window === 'undefined') {
    return { tab: 'opportunities', ticker: 'BBCA' };
  }

  // Check search query parameters: ?tab=terminal&ticker=BBCA
  const searchParams = new URLSearchParams(window.location.search);
  let tabParam = searchParams.get('tab') as TabType | null;
  let tickerParam = searchParams.get('ticker') || searchParams.get('stock');

  // Check hash: #terminal?ticker=BBCA or #power_map or direct ticker like #BBCA
  const hash = window.location.hash.replace(/^#\/?/, '');
  if (hash) {
    const [hashPath, hashQuery] = hash.split('?');
    if (hashPath) {
      if (['opportunities', 'terminal', 'power_map', 'big_money', 'simulator', 'trading_plan', 'ingestion'].includes(hashPath)) {
        tabParam = hashPath as TabType;
      } else if (/^[A-Za-z0-9]{4,5}$/.test(hashPath)) {
        tabParam = 'terminal';
        tickerParam = hashPath.toUpperCase();
      }
    }
    if (hashQuery) {
      const hashParams = new URLSearchParams(hashQuery);
      if (hashParams.get('ticker')) tickerParam = hashParams.get('ticker');
      if (hashParams.get('stock')) tickerParam = hashParams.get('stock');
      if (hashParams.get('tab')) tabParam = hashParams.get('tab') as TabType;
    }
  }

  const validTabs: TabType[] = [
    'opportunities',
    'terminal',
    'power_map',
    'big_money',
    'simulator',
    'trading_plan',
    'ingestion',
  ];
  const tab = tabParam && validTabs.includes(tabParam) ? tabParam : 'opportunities';
  const ticker = (tickerParam || 'BBCA').toUpperCase();

  return { tab, ticker };
}

function syncRouteToUrl(tab: TabType, ticker: string, replace = false) {
  if (typeof window === 'undefined') return;

  let newHash = `#${tab}`;
  if (tab === 'terminal') {
    newHash += `?ticker=${ticker.toUpperCase()}`;
  }

  // Automatically update document title for crisp browser bookmarks (Ctrl+D)
  if (tab === 'terminal') {
    document.title = `${ticker.toUpperCase()} • RitelInsight Terminal`;
  } else if (tab === 'opportunities') {
    document.title = 'Screener • RitelInsight';
  } else if (tab === 'power_map') {
    document.title = 'Tycoons & Power Map • RitelInsight';
  } else if (tab === 'simulator') {
    document.title = 'Strategy Lab • RitelInsight';
  } else if (tab === 'big_money') {
    document.title = 'Big Money • RitelInsight';
  } else if (tab === 'trading_plan') {
    document.title = 'Plan & Journal • RitelInsight';
  } else if (tab === 'ingestion') {
    document.title = 'Data Center • RitelInsight';
  }

  if (window.location.hash !== newHash) {
    if (replace) {
      window.history.replaceState(null, '', newHash);
    } else {
      window.history.pushState(null, '', newHash);
    }
  }
}

export const App: React.FC = () => {
  const initialRoute = parseRouteFromUrl();
  const [activeTab, setActiveTab] = useState<TabType>(initialRoute.tab);
  const [selectedTicker, setSelectedTicker] = useState<string>(initialRoute.ticker);
  const [memoCompany, setMemoCompany] = useState<Company | null>(null);
  const [isWatchlistOpen, setIsWatchlistOpen] = useState<boolean>(false);
  const [alerts] = useState<LiveAlert[]>([]);

  const { data, loading, error, reload } = useDashboardData();
  const { isConnected, lastEvent } = useLiveStream();
  const { watchlist, isStarred, toggleStar, removeStar } = useWatchlist();

  // Sync route on mount and listen to browser Back/Forward (popstate/hashchange)
  useEffect(() => {
    syncRouteToUrl(activeTab, selectedTicker, true);

    const handleUrlChange = () => {
      const { tab, ticker } = parseRouteFromUrl();
      setActiveTab(tab);
      setSelectedTicker(ticker);
    };

    window.addEventListener('popstate', handleUrlChange);
    window.addEventListener('hashchange', handleUrlChange);

    return () => {
      window.removeEventListener('popstate', handleUrlChange);
      window.removeEventListener('hashchange', handleUrlChange);
    };
  }, []);

  // Handle ingestion completion or live anomalies from WebSocket
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type === 'ingestion_completed') {
      console.log('[WebSocket] Ingestion event received -> reloading dashboard data');
      reload();
    } else if (lastEvent.type === 'stealth_accumulation' && lastEvent.ticker) {
      // Do not surface stealth/institutional claims: broker attribution is unavailable.
      console.log(
        '[WebSocket] stealth_accumulation event ignored (attribution unavailable):',
        lastEvent.ticker,
      );
    }
  }, [lastEvent, reload]);

  const handleSelectTab = (tab: TabType) => {
    setActiveTab(tab);
    syncRouteToUrl(tab, selectedTicker);
  };

  const handleSelectStock = (ticker: string) => {
    const upper = ticker.toUpperCase();
    setSelectedTicker(upper);
    setActiveTab('terminal');
    syncRouteToUrl('terminal', upper);
  };

  const handleSelectTicker = (ticker: string) => {
    const upper = ticker.toUpperCase();
    setSelectedTicker(upper);
    syncRouteToUrl('terminal', upper);
  };

  const handleOpenMemo = (company: Company) => {
    setMemoCompany(company);
  };

  return (
    <div className="app-container">
      <Header
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
        isConnected={isConnected}
        watchlistCount={watchlist.length}
        onOpenWatchlist={() => setIsWatchlistOpen(true)}
        onOpenAlerts={() => setIsWatchlistOpen(true)}
        unreadAlertsCount={alerts.length}
      />

      <main className="main-container" style={{ padding: '1.5rem 2rem' }}>
        {/* Production Screener + Strategy Lab + Data Center do not require network_alpha blob */}
        {activeTab === 'opportunities' && (
          <ScreenerTab onSelectTicker={handleSelectStock} />
        )}
        {activeTab === 'big_money' && <BigMoneyTab selectedTicker={selectedTicker} />}
        {activeTab === 'trading_plan' && <TradingPlanTab />}
        <Suspense fallback={<TabFallback />}>
          {activeTab === 'simulator' && (
            <BacktesterTab onSelectStock={handleSelectStock} />
          )}
          {activeTab === 'ingestion' && (
            <IngestionTab lastLiveEvent={lastEvent} />
          )}
        </Suspense>

        {error && !data && (activeTab === 'terminal' || activeTab === 'power_map') && (
          <div className="error-banner">
            <AlertTriangle size={48} />
            <h2>Data Unavailable</h2>
            <p>{error}</p>
            <p>Ensure that the backend ingestion pipeline or mock file has run:</p>
            <code>uv run idx all && uv run idx serve</code>
          </div>
        )}

        {loading && !data && (activeTab === 'terminal' || activeTab === 'power_map') && (
          <div style={{ textAlign: 'center', padding: '4rem', color: 'var(--text-secondary)' }}>
            <p style={{ fontSize: '1.2rem' }}>Loading quantitative intelligence...</p>
          </div>
        )}

        {data && (
          <Suspense fallback={<TabFallback />}>
            {activeTab === 'terminal' && (
              <ChartTab
                companies={data.companies}
                screenerLastUpdated={data.last_updated}
                selectedTicker={selectedTicker}
                onSelectTicker={handleSelectTicker}
                lastLiveEvent={lastEvent}
                onOpenMemo={handleOpenMemo}
                isStarred={isStarred}
                onToggleStar={toggleStar}
              />
            )}

            {activeTab === 'power_map' && (
              <PowerMapTab
                companies={data.companies}
                superInsiders={data.super_insiders}
                conglomerates={data.conglomerates}
                onSelectCompany={handleSelectStock}
              />
            )}
          </Suspense>
        )}
      </main>

      {memoCompany && (
        <Suspense fallback={null}>
          <InvestorMemoModal
            company={memoCompany}
            onClose={() => setMemoCompany(null)}
          />
        </Suspense>
      )}

      <Suspense fallback={null}>
        <WatchlistDrawer
          isOpen={isWatchlistOpen}
          onClose={() => setIsWatchlistOpen(false)}
          watchlist={watchlist}
          onRemoveWatchlist={removeStar}
          onSelectStock={handleSelectStock}
          alerts={alerts}
        />
      </Suspense>

      <footer style={{
        textAlign: 'center',
        padding: '1.5rem',
        borderTop: '1px solid rgba(255, 255, 255, 0.06)',
        color: 'var(--text-secondary)',
        fontSize: '0.8rem',
      }}>
        <p style={{ margin: 0 }}>
          RitelInsight &copy; 2026 &bull; Decision support for Indonesia Stock Exchange market data (research use).
        </p>
      </footer>
    </div>
  );
};

export default App;
