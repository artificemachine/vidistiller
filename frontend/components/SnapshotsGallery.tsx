'use client';

import { useState } from 'react';

interface Snapshot {
  id: number;
  image_url: string;
  timestamp: number;
  detected_text?: string;
}

interface SnapshotsGalleryProps {
  snapshots: Snapshot[];
  onDelete?: (snapshotId: number) => void;
  externalSelectedIndex?: number;
  onSelectedIndexChange?: (index: number) => void;
}

export default function SnapshotsGallery({ snapshots, onDelete, externalSelectedIndex, onSelectedIndexChange }: SnapshotsGalleryProps) {
  const [internalIndex, setInternalIndex] = useState(0);

  if (!snapshots || snapshots.length === 0) {
    return <div className="text-gray-500 dark:text-gray-400 text-sm">no snapshots captured yet. use the player above to capture frames.</div>;
  }

  // Use external index if provided; -1 means "select last"
  const rawIndex = externalSelectedIndex !== undefined ? externalSelectedIndex : internalIndex;
  const safeIndex = rawIndex < 0 ? snapshots.length - 1 : Math.min(rawIndex, snapshots.length - 1);
  const current = snapshots[safeIndex];

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  // Strip /api suffix if present to get base URL for static files
  const baseUrl = apiUrl.replace(/\/api\/?$/, '');

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-3">captured snapshots ({snapshots.length})</h3>

      {/* Main preview */}
      <div className="mb-3">
        <div className="relative bg-gray-200 dark:bg-gray-700 rounded-lg overflow-hidden" style={{ aspectRatio: '16/9' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`${baseUrl}${current.image_url}`}
            alt={`snapshot at ${formatTime(current.timestamp)}`}
            className="w-full h-full object-contain"
          />
        </div>
        <div className="flex justify-between items-center mt-1 text-sm">
          <span className="text-gray-600 dark:text-gray-400 font-mono">{formatTime(current.timestamp)}</span>
          {current.detected_text && (
            <span className="text-gray-500 dark:text-gray-400 truncate ml-2">{current.detected_text}</span>
          )}
        </div>
      </div>

      {/* Thumbnail grid */}
      <div className="grid grid-cols-4 gap-2">
        {snapshots.map((snapshot, index) => (
          <div key={snapshot.id} className="relative group">
            <button
              onClick={() => {
                setInternalIndex(index);
                onSelectedIndexChange?.(index);
              }}
              className={`relative w-full overflow-hidden rounded border-2 ${
                index === safeIndex ? 'border-blue-500' : 'border-gray-300 dark:border-gray-600'
              }`}
              style={{ aspectRatio: '16/9' }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`${baseUrl}${snapshot.image_url}`}
                alt={`thumbnail at ${formatTime(snapshot.timestamp)}`}
                className="w-full h-full object-cover"
              />
              <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs px-1 py-0.5 text-center font-mono">
                {formatTime(snapshot.timestamp)}
              </span>
            </button>
            {onDelete && (
              <button
                onClick={() => onDelete(snapshot.id)}
                className="absolute top-0.5 right-0.5 bg-red-500 text-white rounded-full w-5 h-5 flex items-center justify-center text-xs opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                title="delete snapshot"
              >
                x
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
