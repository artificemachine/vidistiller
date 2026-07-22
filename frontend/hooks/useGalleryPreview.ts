/**
 * Shared preview-pane helpers for the snapshot/slide gallery components.
 *
 * Both `SnapshotsGallery` and `SlidesGallery` render a main preview whose
 * aspect ratio must follow the frame's real shape: portrait sources
 * (e.g. YouTube Shorts, 9:16) must not be forced into a 16:9 box. The
 * authoritative source is the dimensions the backend measured at capture
 * (`image_width`/`image_height`); a loaded-image natural-size fallback exists
 * for legacy rows that predate the dims columns, then a neutral 16:9.
 *
 * Extracted here so the three-way duplication (state + computation + onLoad
 * handler + time formatter) lives in exactly one place.
 */

import { useCallback, useState } from 'react';

/**
 * Format a number of seconds as `[H:]MM:SS` (hours only when non-zero).
 *
 * Mirrors the shape both galleries previously inlined. Kept as a pure export
 * (not part of the hook) so thumbnail grids and preview headers can format
 * timestamps without subscribing to preview state.
 */
export function formatGalleryTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export interface UseGalleryPreviewResult {
  /** CSS `aspect-ratio` value to apply to the preview box. */
  previewAspect: string;
  /** Attach to the preview `<img onLoad>`; only acts when backend dims are absent. */
  onImageLoad: (e: React.SyntheticEvent<HTMLImageElement>) => void;
}

/**
 * Preview aspect-ratio state for a gallery pane.
 *
 * @param width  Backend-captured `image_width` for the currently-shown item (optional).
 * @param height Backend-captured `image_height` for the currently-shown item (optional).
 *
 * When both dims are present they win immediately, before the image ever loads
 * (so portrait frames never flash in a 16:9 box). Otherwise the hook falls back
 * to the loaded image's natural size, then a neutral 16:9.
 */
export function useGalleryPreview(width?: number, height?: number): UseGalleryPreviewResult {
  // Fallback aspect from the loaded image's natural size, used only when the
  // backend didn't record image_width/image_height (legacy rows).
  const [loadedAspect, setLoadedAspect] = useState<string | null>(null);

  const previewAspect =
    width && height ? `${width}/${height}` : loadedAspect ?? '16/9';

  const onImageLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    // Only used when the backend didn't record dimensions.
    const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
    if (w && h) setLoadedAspect(`${w}/${h}`);
  }, []);

  return { previewAspect, onImageLoad };
}
