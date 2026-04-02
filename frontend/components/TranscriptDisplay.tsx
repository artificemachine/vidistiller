'use client';

import { useState } from 'react';

interface TranscriptSegment {
  id: string;
  text: string;
  start_time: number;
  end_time: number;
  speaker?: string;
}

interface TranscriptDisplayProps {
  segments: TranscriptSegment[];
  onTimestampClick?: (seconds: number) => void;
}

export default function TranscriptDisplay({ segments, onTimestampClick }: TranscriptDisplayProps) {
  const [searchTerm, setSearchTerm] = useState('');

  const filtered = segments.filter((seg) =>
    seg.text.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="w-full h-full overflow-y-auto p-4">
      <h2 className="text-lg font-bold mb-3">transcript</h2>

      <input
        type="text"
        placeholder="search transcript..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        className="w-full px-3 py-1.5 mb-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
      />

      <div className="space-y-2">
        {filtered.map((segment) => (
          <div key={segment.id} className="border-l-4 border-blue-500 pl-3 py-1">
            <div className="flex items-center justify-between mb-0.5">
              {segment.speaker && <span className="font-semibold text-sm">{segment.speaker}</span>}
              <button
                onClick={() => onTimestampClick?.(segment.start_time)}
                className={`text-xs font-mono ${
                  onTimestampClick
                    ? 'text-blue-600 hover:text-blue-800 hover:underline cursor-pointer'
                    : 'text-gray-500'
                }`}
              >
                {formatTime(segment.start_time)}
              </button>
            </div>
            <p className="text-gray-800 text-sm">{segment.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
