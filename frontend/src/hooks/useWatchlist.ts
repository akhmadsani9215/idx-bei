import { useCallback, useEffect, useState } from 'react';
import type { WatchlistItem } from '../types';
import {
  createAuthSession,
  deleteWatchlistItem,
  fetchWatchlist,
  getStoredSessionId,
  postWatchlistItem,
  setStoredSessionId,
} from '../services/api';

/** Backend-backed watchlist. Never trusts client user_id. No fake seed prices. */
export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(() => getStoredSessionId());
  const [authNote, setAuthNote] = useState<string>('AUTH NOT_CONFIGURED — local opaque session');
  const [loading, setLoading] = useState(false);

  const ensureSession = useCallback(async (): Promise<string> => {
    const existing = getStoredSessionId();
    if (existing) return existing;
    const created = await createAuthSession();
    const sid = created.session_id as string;
    setStoredSessionId(sid);
    setSessionId(sid);
    if (created.auth?.status) {
      setAuthNote(`AUTH ${created.auth.status} — local opaque session`);
    }
    return sid;
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const sid = await ensureSession();
      const data = await fetchWatchlist(sid);
      const items = (data.items || []).map((it: any) => ({
        code: it.ticker,
        name: it.company || it.ticker,
        sector: it.group,
        price: it.current_price ?? undefined,
        score: it.score ?? undefined,
        addedAt: it.added_at || new Date().toISOString(),
        notes: it.notes,
        tags: it.tags,
        setup: it.setup,
        signal: it.signal,
        entry: it.entry,
        tp: it.tp,
        cl: it.cl,
        rr: it.rr,
      }));
      setWatchlist(items);
    } catch (e) {
      console.warn('Watchlist reload failed', e);
      setWatchlist([]);
    } finally {
      setLoading(false);
    }
  }, [ensureSession]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const isStarred = (code: string): boolean =>
    watchlist.some((item) => item.code.toUpperCase() === code.toUpperCase());

  const toggleStar = async (company: {
    code: string;
    name: string;
    sector?: string;
    close?: number | null;
    price?: number | null;
    daily_change?: number | null;
    score?: any;
  }) => {
    const code = company.code.toUpperCase();
    const sid = await ensureSession();
    if (isStarred(code)) {
      await deleteWatchlistItem(sid, code);
    } else {
      const snapshotPrice = company.close ?? company.price ?? null;
      await postWatchlistItem(sid, {
        ticker: code,
        company: company.name,
        group: company.sector || 'default',
        current_price: snapshotPrice == null ? undefined : Number(snapshotPrice),
        score:
          typeof company.score === 'object' ? company.score?.total : company.score,
      });
    }
    await reload();
  };

  const removeStar = async (code: string) => {
    const sid = await ensureSession();
    try {
      await deleteWatchlistItem(sid, code);
    } catch {
      /* missing ok */
    }
    await reload();
  };

  return {
    watchlist,
    isStarred,
    toggleStar,
    removeStar,
    sessionId,
    authNote,
    loading,
    reload,
  };
}
