'use client';

import { useState } from 'react';
import ThemeToggle from '../ThemeToggle';

interface ActivityBarProps {
  sidebarVisible: boolean;
  bottomVisible: boolean;
  logsVisible: boolean;
  hasBottom?: boolean;
  onToggleSidebar: () => void;
  onToggleBottom: () => void;
  onToggleLogs: () => void;
  hasSlideText?: boolean;
  slideTextVisible?: boolean;
  onToggleSlideText?: () => void;
  onSaveLayout?: () => void;
}

function BarButton({
  onClick,
  active,
  label,
  desc,
  children,
}: {
  onClick: () => void;
  active: boolean;
  label: string;
  desc: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative group">
      <button
        onClick={onClick}
        aria-label={label}
        className={`p-2 rounded transition-colors ${
          active ? 'bg-border-dark text-text-light' : 'text-text-light/40 hover:text-text-light'
        }`}
      >
        {children}
      </button>
      {/* Tooltip */}
      <div className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-3 z-50 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
        <div className="bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 shadow-lg whitespace-nowrap">
          <p className="text-[11px] font-semibold text-text-light leading-tight">{label}</p>
          <p className="text-[10px] text-text-light/50 leading-tight mt-0.5">{desc}</p>
        </div>
      </div>
    </div>
  );
}

export default function ActivityBar({
  sidebarVisible,
  bottomVisible,
  logsVisible,
  hasBottom = true,
  onToggleSidebar,
  onToggleBottom,
  onToggleLogs,
  hasSlideText,
  slideTextVisible,
  onToggleSlideText,
  onSaveLayout,
}: ActivityBarProps) {
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    onSaveLayout?.();
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div className="w-[60px] bg-card-dark flex flex-col items-center py-5 gap-5 shrink-0">
      <BarButton
        onClick={onToggleSidebar}
        active={sidebarVisible}
        label="Transcript"
        desc="toggle transcript panel"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <line x1="7" y1="3" x2="7" y2="17" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </BarButton>

      <BarButton
        onClick={onToggleBottom}
        active={bottomVisible}
        label="Snapshots"
        desc="toggle snapshots gallery"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <line x1="2" y1="12" x2="18" y2="12" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </BarButton>

      {hasBottom && (
        <BarButton
          onClick={onToggleLogs}
          active={logsVisible}
          label="Logs"
          desc="toggle processing logs"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="7" x2="15" y2="7" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="10" x2="12" y2="10" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="13" x2="14" y2="13" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </BarButton>
      )}

      {hasSlideText && (
        <BarButton
          onClick={onToggleSlideText!}
          active={!!slideTextVisible}
          label="Slide notes"
          desc="toggle slide OCR & transcript"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="7" x2="15" y2="7" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="10" x2="15" y2="10" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="13" x2="11" y2="13" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </BarButton>
      )}

      {/* Spacer + save layout + theme toggle at bottom */}
      <div className="mt-auto flex flex-col items-center gap-3 border-t border-border-dark pt-3">
        <div className="relative group">
          <button
            onClick={handleSave}
            className={`p-2 rounded transition-colors ${saved ? 'text-green-400' : 'text-text-light/40 hover:text-text-light'}`}
          >
            {saved ? (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <polyline points="4,10 8,14 16,6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="3" y="2" width="14" height="16" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
                <rect x="6.5" y="2" width="7" height="5" rx="0.5" stroke="currentColor" strokeWidth="1.5" />
                <rect x="5.5" y="11" width="9" height="5" rx="0.5" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            )}
          </button>
          <div className="pointer-events-none absolute left-full top-1/2 -translate-y-1/2 ml-3 z-50 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
            <div className="bg-gray-900 border border-gray-700 rounded-md px-2.5 py-1.5 shadow-lg whitespace-nowrap">
              <p className="text-[11px] font-semibold text-text-light leading-tight">Save layout</p>
              <p className="text-[10px] text-text-light/50 leading-tight mt-0.5">set current panel sizes as default</p>
            </div>
          </div>
        </div>
        <ThemeToggle compact />
      </div>
    </div>
  );
}
