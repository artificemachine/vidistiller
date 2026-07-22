'use client';

import { useState } from 'react';

export interface SlideItem {
  id: number;
  slide_number: number;
  start_timestamp: number;
  end_timestamp: number;
  image_url?: string;
  ocr_text?: string;
  transcript_text?: string;
  is_incremental_build?: boolean;
  ssim_transition_score?: number;
}

interface SlidesGalleryProps {
  slides: SlideItem[];
  onSlideClick?: (slide: SlideItem) => void;
  externalSelectedIndex?: number;
  onSelectedIndexChange?: (index: number) => void;
}

export default function SlidesGallery({
  slides,
  onSlideClick,
  externalSelectedIndex,
  onSelectedIndexChange,
}: SlidesGalleryProps) {
  const [internalIndex, setInternalIndex] = useState(0);
  // Derived from the loaded image's natural dimensions so portrait sources
  // (e.g. Shorts, 9:16) render at their true aspect instead of a forced 16:9.
  const [previewAspect, setPreviewAspect] = useState('16/9');

  if (!slides || slides.length === 0) {
    return (
      <div className="text-gray-500 dark:text-gray-400 text-sm">
        no slides detected yet. slide detection runs after transcript processing completes.
      </div>
    );
  }

  const rawIndex = externalSelectedIndex !== undefined ? externalSelectedIndex : internalIndex;
  const safeIndex = rawIndex < 0 ? slides.length - 1 : Math.min(rawIndex, slides.length - 1);
  const current = slides[safeIndex];

  const formatTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
  const baseUrl = apiUrl.replace(/\/api\/?$/, '');

  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-3">
        detected slides ({slides.length})
      </h3>

      {/* Main preview */}
      <div className="mb-3">
        {current.image_url ? (
          <div className="relative bg-gray-200 dark:bg-gray-700 rounded-lg overflow-hidden mx-auto" style={{ aspectRatio: previewAspect, maxHeight: '70vh' }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={`${baseUrl}${current.image_url}`}
              alt={`slide ${current.slide_number}`}
              className="w-full h-full object-contain"
              onLoad={(e) => {
                const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
                if (w && h) setPreviewAspect(`${w}/${h}`);
              }}
            />
            <div className="absolute top-2 left-2 bg-black/70 text-white text-xs px-2 py-1 rounded font-mono">
              slide {current.slide_number}
            </div>
            {current.is_incremental_build && (
              <div className="absolute top-2 right-2 bg-yellow-500/80 text-white text-xs px-2 py-1 rounded">
                incremental
              </div>
            )}
          </div>
        ) : (
          <div className="bg-gray-200 dark:bg-gray-700 rounded-lg flex items-center justify-center" style={{ aspectRatio: '16/9' }}>
            <span className="text-gray-500 dark:text-gray-400 text-sm">no image</span>
          </div>
        )}
        <div className="flex justify-between items-center mt-1 text-sm">
          <span className="text-gray-600 dark:text-gray-400 font-mono">
            {formatTime(current.start_timestamp)} - {formatTime(current.end_timestamp)}
          </span>
        </div>
      </div>

      {/* Thumbnail grid */}
      <div className="grid grid-cols-4 gap-2">
        {slides.map((slide, index) => (
          <button
            key={slide.id}
            onClick={() => {
              setInternalIndex(index);
              onSelectedIndexChange?.(index);
              onSlideClick?.(slide);
            }}
            className={`relative w-full overflow-hidden rounded border-2 ${
              index === safeIndex ? 'border-blue-500' : 'border-gray-300 dark:border-gray-600'
            }`}
            style={{ aspectRatio: '16/9' }}
          >
            {slide.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`${baseUrl}${slide.image_url}`}
                alt={`slide ${slide.slide_number}`}
                className="w-full h-full object-contain"
              />
            ) : (
              <div className="w-full h-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
                <span className="text-gray-400 text-[10px]">{slide.slide_number}</span>
              </div>
            )}
            <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs px-1 py-0.5 text-center font-mono">
              {slide.slide_number}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
