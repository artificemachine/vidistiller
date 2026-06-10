'use client';

import { useCallback, useEffect, useState } from 'react';
import { Group, Panel, usePanelRef, useDefaultLayout } from 'react-resizable-panels';
import ActivityBar from './ActivityBar';
import ResizeHandle from './ResizeHandle';
import PanelHeader from './PanelHeader';

interface WorkspaceLayoutProps {
  sidebar: React.ReactNode;
  main: (zoom: number) => React.ReactNode;
  logs?: React.ReactNode;
  bottom: React.ReactNode;
  sidebarActions?: React.ReactNode;
  sidebarTitle?: string;
  logsCollapsed?: boolean;
  slideText?: React.ReactNode;
}

const UI_STATE_KEY = 'vidistiller-workspace-state';

function readUIState() {
  try { return JSON.parse(localStorage.getItem(UI_STATE_KEY) || '{}'); } catch { return {}; }
}

export default function WorkspaceLayout({ sidebar, main, logs, bottom, sidebarActions, sidebarTitle, logsCollapsed, slideText }: WorkspaceLayoutProps) {
  const sidebarPanelRef = usePanelRef();
  const [sidebarVisible, setSidebarVisible] = useState(true);
  const [bottomVisible, setBottomVisible] = useState(true);
  const [logsVisible, setLogsVisible] = useState(true);
  const [slideTextVisible, setSlideTextVisible] = useState(true);
  const [playerZoom, setPlayerZoom] = useState(40);
  const [hydrated, setHydrated] = useState(false);

  // Read saved state from localStorage on client mount (after SSR hydration)
  useEffect(() => {
    const saved = readUIState();
    if (saved.sidebarVisible !== undefined) setSidebarVisible(saved.sidebarVisible);
    if (saved.bottomVisible !== undefined) setBottomVisible(saved.bottomVisible);
    if (saved.logsVisible !== undefined) setLogsVisible(saved.logsVisible);
    if (saved.slideTextVisible !== undefined) setSlideTextVisible(saved.slideTextVisible);
    if (saved.playerZoom !== undefined) setPlayerZoom(saved.playerZoom);
    setHydrated(true);
  }, []);

  // Persist state to localStorage whenever it changes (skip initial server render)
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(UI_STATE_KEY, JSON.stringify({ sidebarVisible, bottomVisible, logsVisible, slideTextVisible, playerZoom }));
    } catch {}
  }, [hydrated, sidebarVisible, bottomVisible, logsVisible, slideTextVisible, playerZoom]);

  // Sync logs visibility with external collapse signal
  useEffect(() => {
    if (logsCollapsed) setLogsVisible(false);
  }, [logsCollapsed]);

  const horizontalLayout = useDefaultLayout({ id: 'workspace-horizontal' });

  const toggleSidebar = useCallback(() => {
    const panel = sidebarPanelRef.current;
    if (!panel) return;
    if (panel.isCollapsed()) {
      panel.expand();
      setSidebarVisible(true);
    } else {
      panel.collapse();
      setSidebarVisible(false);
    }
  }, [sidebarPanelRef]);

  const toggleBottom = useCallback(() => {
    setBottomVisible((v) => !v);
  }, []);

  const toggleLogs = useCallback(() => {
    setLogsVisible((v) => !v);
  }, []);

  const toggleSlideText = useCallback(() => {
    setSlideTextVisible((v) => !v);
  }, []);

  const showLogs = !!(logs && logsVisible);
  const showBottom = bottomVisible && !!bottom;

  return (
    <div className="flex h-full w-full overflow-hidden">
      <ActivityBar
        sidebarVisible={sidebarVisible}
        bottomVisible={logsVisible}
        logsVisible={bottomVisible}
        hasBottom={!!bottom}
        onToggleSidebar={toggleSidebar}
        onToggleBottom={toggleLogs}
        onToggleLogs={toggleBottom}
        hasSlideText={!!slideText}
        slideTextVisible={slideTextVisible}
        onToggleSlideText={toggleSlideText}
      />

      <Group
        orientation="horizontal"
        defaultLayout={horizontalLayout.defaultLayout}
        onLayoutChanged={horizontalLayout.onLayoutChanged}
      >
        {/* Sidebar: Transcript */}
        <Panel
          id="sidebar"
          panelRef={sidebarPanelRef}
          defaultSize="25%"
          minSize="15%"
          collapsible
          collapsedSize="0%"
          onResize={(size) => {
            if (size.asPercentage === 0) setSidebarVisible(false);
            else setSidebarVisible(true);
          }}
        >
          <div className="flex flex-col h-full bg-border-light dark:bg-border-dark border-r border-border-light dark:border-border-dark">
            <PanelHeader
              title={sidebarTitle ?? "transcript"}
              collapsed={!sidebarVisible}
              onToggleCollapse={toggleSidebar}
              actions={sidebarActions}
            />
            <div className="flex-1 overflow-y-auto">{sidebar}</div>
          </div>
        </Panel>

        <ResizeHandle direction="horizontal" />

        {/* Main content area: vertical split */}
        <Panel id="content" defaultSize="75%" minSize="30%">
          <Group orientation="vertical">
            {/* Top: Player */}
            <Panel id="player" defaultSize={showLogs || showBottom ? '45%' : '100%'} minSize="20%">
              <div className="flex flex-col h-full bg-card-light dark:bg-card-dark">
                <PanelHeader
                  title="player"
                  actions={
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => setPlayerZoom((v) => Math.max(10, v - 1))}
                        className="text-[11px] text-text-dark/40 hover:text-text-dark dark:text-text-light/40 dark:hover:text-text-light w-5 h-5 flex items-center justify-center rounded hover:bg-border-light dark:hover:bg-border-dark transition-colors"
                        title="zoom out"
                      >−</button>
                      <input
                        type="range"
                        min={10}
                        max={100}
                        step={1}
                        value={playerZoom}
                        onChange={(e) => setPlayerZoom(Number(e.target.value))}
                        className="w-20 h-1 accent-primary cursor-pointer"
                        title={`Zoom: ${playerZoom}%`}
                      />
                      <button
                        onClick={() => setPlayerZoom((v) => Math.min(100, v + 1))}
                        className="text-[11px] text-text-dark/40 hover:text-text-dark dark:text-text-light/40 dark:hover:text-text-light w-5 h-5 flex items-center justify-center rounded hover:bg-border-light dark:hover:bg-border-dark transition-colors"
                        title="zoom in"
                      >+</button>
                      <button
                        onClick={() => setPlayerZoom(40)}
                        className="text-[10px] text-text-dark/40 hover:text-text-dark dark:text-text-light/40 dark:hover:text-text-light font-mono min-w-[32px] text-center"
                        title="reset zoom"
                      >
                        {playerZoom}%
                      </button>
                    </div>
                  }
                />
                <div className="flex-1 overflow-auto p-4">
                  {main(playerZoom)}
                </div>
              </div>
            </Panel>

            {/* Middle: Snapshots */}
            {showLogs && (
              <>
                <ResizeHandle direction="vertical" />
                <Panel id="logs" defaultSize="20%" minSize="10%">
                  <div className="flex flex-col h-full bg-card-light dark:bg-card-dark border-t border-border-light dark:border-border-dark">
                    <PanelHeader title="snapshots" />
                    <div className="flex-1 overflow-y-auto">{logs}</div>
                  </div>
                </Panel>
              </>
            )}

            {/* Bottom: Processing Logs */}
            {showBottom && (
              <>
                <ResizeHandle direction="vertical" />
                <Panel id="bottom" defaultSize={showLogs ? '35%' : '55%'} minSize="15%">
                  <div className="flex flex-col h-full bg-card-light dark:bg-card-dark border-t border-border-light dark:border-border-dark">
                    <PanelHeader title="processing logs" />
                    <div className="flex-1 overflow-y-auto p-4">{bottom}</div>
                  </div>
                </Panel>
              </>
            )}

            {/* Slide Notes: OCR + transcript for the selected slide */}
            {!!slideText && slideTextVisible && (
              <>
                <ResizeHandle direction="vertical" />
                <Panel id="slide-notes" defaultSize="25%" minSize="10%">
                  <div className="flex flex-col h-full bg-card-light dark:bg-card-dark border-t border-border-light dark:border-border-dark">
                    <PanelHeader title="slide notes" />
                    <div className="flex-1 overflow-y-auto">{slideText}</div>
                  </div>
                </Panel>
              </>
            )}
          </Group>
        </Panel>
      </Group>
    </div>
  );
}
