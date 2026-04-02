'use client';

interface PanelHeaderProps {
  title: string;
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  actions?: React.ReactNode;
}

export default function PanelHeader({ title, collapsed, onToggleCollapse, actions }: PanelHeaderProps) {
  return (
    <div className="flex items-center justify-between px-3 py-1.5 bg-bg-light dark:bg-card-dark border-b border-border-light dark:border-border-dark select-none shrink-0">
      <span className="text-xs font-semibold text-text-dark/60 dark:text-text-light/60 uppercase tracking-wide">{title}</span>
      <div className="flex items-center gap-2">
        {actions}
        {onToggleCollapse && (
          <button
            onClick={onToggleCollapse}
            className="p-0.5 rounded hover:bg-border-light dark:hover:bg-border-dark text-text-dark/40 hover:text-text-dark dark:text-text-light/40 dark:hover:text-text-light transition-colors"
            title={collapsed ? 'expand panel' : 'collapse panel'}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path
                d={collapsed ? 'M5 3l4 4-4 4' : 'M3 5l4 4 4-4'}
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
