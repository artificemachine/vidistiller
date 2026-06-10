'use client';

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
}: ActivityBarProps) {
  return (
    <div className="w-[60px] bg-card-dark flex flex-col items-center py-5 gap-5 shrink-0">
      {/* Transcript toggle */}
      <button
        onClick={onToggleSidebar}
        className={`p-2 rounded transition-colors ${
          sidebarVisible ? 'bg-border-dark text-text-light' : 'text-text-light/40 hover:text-text-light'
        }`}
        title="toggle transcript"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <line x1="7" y1="3" x2="7" y2="17" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>

      {/* Snapshots / bottom panel toggle */}
      <button
        onClick={onToggleBottom}
        className={`p-2 rounded transition-colors ${
          bottomVisible ? 'bg-border-dark text-text-light' : 'text-text-light/40 hover:text-text-light'
        }`}
        title="toggle snapshots"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <line x1="2" y1="12" x2="18" y2="12" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>

      {/* Logs panel toggle — only shown when there is log content */}
      {hasBottom && <button
        onClick={onToggleLogs}
        className={`p-2 rounded transition-colors ${
          logsVisible ? 'bg-border-dark text-text-light' : 'text-text-light/40 hover:text-text-light'
        }`}
        title="toggle logs"
      >
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
          <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <line x1="5" y1="7" x2="15" y2="7" stroke="currentColor" strokeWidth="1.5" />
          <line x1="5" y1="10" x2="12" y2="10" stroke="currentColor" strokeWidth="1.5" />
          <line x1="5" y1="13" x2="14" y2="13" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>}

      {/* Slide notes toggle — only visible in slide_aware mode */}
      {hasSlideText && (
        <button
          onClick={onToggleSlideText}
          className={`p-2 rounded transition-colors ${
            slideTextVisible ? 'bg-border-dark text-text-light' : 'text-text-light/40 hover:text-text-light'
          }`}
          title="toggle slide notes"
        >
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="3" width="16" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="7" x2="15" y2="7" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="10" x2="15" y2="10" stroke="currentColor" strokeWidth="1.5" />
            <line x1="5" y1="13" x2="11" y2="13" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </button>
      )}

      {/* Spacer + theme toggle at bottom */}
      <div className="mt-auto border-t border-border-dark pt-2">
        <ThemeToggle compact />
      </div>
    </div>
  );
}
