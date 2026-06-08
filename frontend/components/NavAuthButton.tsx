'use client';

import Link from 'next/link';
import { useRef, useState, useEffect, useCallback } from 'react';
import { useAuthStore } from '@/lib/authStore';
import NavStatusBadge from './NavStatusBadge';

const SETUPS_KEY = 'vidistiller-ui-setups';

interface UISetup {
  name: string;
  savedAt: string;
  data: Record<string, string | null>;
}

function loadSetups(): UISetup[] {
  try { return JSON.parse(localStorage.getItem(SETUPS_KEY) || '[]'); } catch { return []; }
}

function saveSetups(setups: UISetup[]) {
  localStorage.setItem(SETUPS_KEY, JSON.stringify(setups));
}

const UI_CAPTURE_PREFIXES = ['workspace', 'react-resizable-panels', 'theme', 'vidistiller-theme', 'vidistiller-workspace'];

function captureSnapshot(): Record<string, string | null> {
  const snapshot: Record<string, string | null> = {};
  for (const key of Object.keys(localStorage)) {
    if (key === SETUPS_KEY || key === 'vidistiller-ui-snapshot') continue;
    if (UI_CAPTURE_PREFIXES.some((p) => key.startsWith(p))) {
      snapshot[key] = localStorage.getItem(key);
    }
  }
  return snapshot;
}

function restoreSnapshot(data: Record<string, string | null>) {
  for (const [key, value] of Object.entries(data)) {
    if (value !== null) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  }
}

export default function NavAuthButton() {
  const { user, isAuthenticated, isLoading, logout } = useAuthStore();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<'menu' | 'save' | 'load'>('menu');
  const [saveName, setSaveName] = useState('');
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  const [setups, setSetups] = useState<UISetup[]>([]);
  const [feedback, setFeedback] = useState('');
  const ref = useRef<HTMLDivElement>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setView('menu');
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  useEffect(() => () => clearTimeout(feedbackTimer.current), []);

  const scheduleFeedback = useCallback((msg: string, ms: number) => {
    clearTimeout(feedbackTimer.current);
    setFeedback(msg);
    feedbackTimer.current = setTimeout(() => setFeedback(''), ms);
  }, []);

  function openLoad() {
    setSetups(loadSetups());
    setView('load');
  }

  function openSave() {
    setSaveName('');
    setConfirmOverwrite(false);
    setView('save');
  }

  function handleSave(force = false) {
    const name = saveName.trim() || `setup ${new Date().toLocaleString()}`;
    const existing = loadSetups();
    if (!force && existing.some((s) => s.name === name)) {
      setConfirmOverwrite(true);
      return;
    }
    const newSetup: UISetup = { name, savedAt: new Date().toISOString(), data: captureSnapshot() };
    const updated = [newSetup, ...existing.filter((s) => s.name !== name)].slice(0, 3);
    saveSetups(updated);
    localStorage.setItem('vidistiller-ui-snapshot', JSON.stringify(newSetup.data));
    setConfirmOverwrite(false);
    scheduleFeedback('saved!', 2000);
    setOpen(false);
    setView('menu');
  }

  function handleLoad(setup: UISetup) {
    restoreSnapshot(setup.data);
    localStorage.setItem('vidistiller-ui-snapshot', JSON.stringify(setup.data));
    window.location.reload();
  }

  function handleDelete(name: string, e: React.MouseEvent) {
    e.stopPropagation();
    const updated = loadSetups().filter((s) => s.name !== name);
    saveSetups(updated);
    setSetups(updated);
  }

  if (isLoading) {
    return <span className="text-sm text-text-dark/40 dark:text-text-light/40">...</span>;
  }

  if (!isAuthenticated) {
    return (
      <Link href="/login" className="text-text-dark/70 hover:text-text-dark dark:text-text-light/70 dark:hover:text-text-light">
        login
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <NavStatusBadge />
      <Link href="/dashboard" className="text-text-dark/70 hover:text-text-dark dark:text-text-light/70 dark:hover:text-text-light">
        dashboard
      </Link>
      <div ref={ref} className="relative">
        <button
          onClick={() => { setOpen((v) => !v); setView('menu'); }}
          className="flex items-center gap-1 text-sm text-text-dark dark:text-text-light hover:text-primary dark:hover:text-primary transition-colors"
        >
          {user?.username}
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg" className={`transition-transform ${open ? 'rotate-180' : ''}`}>
            <path d="M2 3.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>

        {open && (
          <div className="absolute right-0 mt-2 w-52 bg-card-dark border border-border-dark rounded-lg shadow-lg z-50 overflow-hidden text-[13px]">

            {/* Main menu */}
            {view === 'menu' && (
              <>
                <Link
                  href="/settings"
                  onClick={() => setOpen(false)}
                  className="flex items-center gap-2 px-3 py-2 text-text-light/70 hover:text-text-light hover:bg-border-dark transition-colors"
                >
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle cx="7" cy="7" r="2" stroke="currentColor" strokeWidth="1.3" />
                    <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.93 2.93l1.06 1.06M10.01 10.01l1.06 1.06M2.93 11.07l1.06-1.06M10.01 3.99l1.06-1.06" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
                  </svg>
                  settings
                </Link>
                <button
                  onClick={openSave}
                  className="w-full flex items-center gap-2 px-3 py-2 text-text-light/70 hover:text-text-light hover:bg-border-dark transition-colors"
                >
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M11 13H3a1 1 0 01-1-1V2a1 1 0 011-1h6l3 3v8a1 1 0 01-1 1z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M9 1v3h3M5 9h4M5 11h2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  save ui setup
                </button>
                <button
                  onClick={openLoad}
                  className="w-full flex items-center gap-2 px-3 py-2 text-text-light/70 hover:text-text-light hover:bg-border-dark transition-colors"
                >
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M1 4h12v8a1 1 0 01-1 1H2a1 1 0 01-1-1V4zM1 4V3a1 1 0 011-1h3l1 2H1z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  load ui setup
                </button>
                <div className="border-t border-border-dark" />
                <button
                  onClick={() => {
                    logout();
                    localStorage.removeItem('vidistiller-theme');
                    localStorage.removeItem('theme');
                    localStorage.removeItem('vidistiller-workspace-state');
                    window.location.href = '/api/auth/logout';
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-text-light/50 hover:text-destructive hover:bg-border-dark transition-colors"
                >
                  <svg width="13" height="13" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M5 13H2a1 1 0 01-1-1V2a1 1 0 011-1h3M9.5 10.5L13 7l-3.5-3.5M13 7H5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  logout
                </button>
              </>
            )}

            {/* Save view */}
            {view === 'save' && (
              <div className="p-3 flex flex-col gap-2">
                <div className="flex items-center gap-1 mb-1">
                  <button onClick={() => setView('menu')} className="text-text-light/40 hover:text-text-light transition-colors">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M8 2L4 6l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                  <span className="text-text-light/50 text-[11px]">save ui setup <span className="text-text-light/30">(max 3)</span></span>
                </div>
                <input
                  autoFocus
                  value={saveName}
                  onChange={(e) => { setSaveName(e.target.value); setConfirmOverwrite(false); }}
                  onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                  placeholder="setup name..."
                  className="w-full bg-bg-dark border border-border-dark rounded px-2 py-1 text-text-light text-[12px] placeholder-text-light/30 focus:outline-none focus:border-primary"
                />
                {confirmOverwrite ? (
                  <div className="flex flex-col gap-1">
                    <p className="text-[11px] text-yellow-400">"{saveName.trim()}" already exists. overwrite?</p>
                    <div className="flex gap-1">
                      <button
                        onClick={() => handleSave(true)}
                        className="flex-1 bg-yellow-500/20 hover:bg-yellow-500/30 text-yellow-400 rounded px-2 py-1 text-[12px] font-medium transition-colors"
                      >
                        overwrite
                      </button>
                      <button
                        onClick={() => setConfirmOverwrite(false)}
                        className="flex-1 bg-border-dark hover:bg-border-dark/80 text-text-light/50 rounded px-2 py-1 text-[12px] transition-colors"
                      >
                        cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => handleSave()}
                    className="w-full bg-primary/20 hover:bg-primary/30 text-primary rounded px-2 py-1 text-[12px] font-medium transition-colors"
                  >
                    save
                  </button>
                )}
              </div>
            )}

            {/* Load view */}
            {view === 'load' && (
              <div className="flex flex-col">
                <div className="flex items-center gap-1 px-3 py-2 border-b border-border-dark">
                  <button onClick={() => setView('menu')} className="text-text-light/40 hover:text-text-light transition-colors">
                    <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M8 2L4 6l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  </button>
                  <span className="text-text-light/50 text-[11px]">load ui setup</span>
                </div>
                {setups.length === 0 ? (
                  <p className="px-3 py-3 text-text-light/30 text-[12px]">no setups saved yet</p>
                ) : (
                  setups.map((s) => (
                    <button
                      key={s.name}
                      onClick={() => handleLoad(s)}
                      className="group flex items-center justify-between px-3 py-2 hover:bg-border-dark transition-colors text-left"
                    >
                      <div>
                        <div className="text-text-light/80 group-hover:text-text-light">{s.name}</div>
                        <div className="text-text-light/30 text-[10px]">{new Date(s.savedAt).toLocaleString()}</div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => handleDelete(s.name, e)}
                        className="text-text-light/20 hover:text-destructive transition-colors ml-2"
                        title="delete"
                      >
                        <svg width="11" height="11" viewBox="0 0 12 12" fill="none"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                      </button>
                    </button>
                  ))
                )}
              </div>
            )}
          </div>
        )}
      </div>
      {feedback && (
        <span className="text-[11px] text-primary animate-pulse">{feedback}</span>
      )}
    </div>
  );
}
