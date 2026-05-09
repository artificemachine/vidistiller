'use client';

import { useEffect, useRef, useState, useCallback, useImperativeHandle, forwardRef } from 'react';
import { loadResume, saveResume, clearResume, pruneOldEntries } from '@/lib/videoResume';

const RESUME_SAVE_INTERVAL_MS = 5000;
const RESUME_MIN_OFFSET_S = 5;
const RESUME_END_BUFFER_S = 5;
const RESUME_MAX_AGE_MS = 90 * 24 * 3600 * 1000;

interface YouTubePlayerProps {
  youtubeUrl: string;
  onSnapshot: (timestamp: number) => void;
  disabled?: boolean;
  zoom?: number;
}

export interface YouTubePlayerHandle {
  seekTo: (seconds: number) => void;
  getCurrentTime: () => number;
}

declare global {
  interface Window {
    YT: any;
    onYouTubeIframeAPIReady: (() => void) | undefined;
  }
}

function extractVideoId(url: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=)([\w-]{11})/,
    /(?:youtu\.be\/)([\w-]{11})/,
    /(?:youtube\.com\/embed\/)([\w-]{11})/,
  ];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) return match[1];
  }
  return null;
}

const YouTubePlayer = forwardRef<YouTubePlayerHandle, YouTubePlayerProps>(
  function YouTubePlayer({ youtubeUrl, onSnapshot, disabled, zoom = 100 }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const playerRef = useRef<any>(null);
    const saveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const [isReady, setIsReady] = useState(false);
    const [capturing, setCapturing] = useState(false);

    const videoId = extractVideoId(youtubeUrl);

    useImperativeHandle(ref, () => ({
      seekTo: (seconds: number) => {
        if (playerRef.current && isReady) {
          playerRef.current.seekTo(seconds, true);
        }
      },
      getCurrentTime: () => {
        if (playerRef.current && isReady) {
          return playerRef.current.getCurrentTime();
        }
        return 0;
      },
    }), [isReady]);

    const stopProgressSaver = useCallback(() => {
      if (saveIntervalRef.current) {
        clearInterval(saveIntervalRef.current);
        saveIntervalRef.current = null;
      }
    }, []);

    const persistCurrentTime = useCallback(() => {
      const player = playerRef.current;
      if (!player || !videoId) return;
      try {
        const t = player.getCurrentTime?.() ?? 0;
        const duration = player.getDuration?.() ?? 0;
        if (duration > 0 && t >= duration - RESUME_END_BUFFER_S) {
          clearResume(videoId);
          return;
        }
        if (t >= RESUME_MIN_OFFSET_S) {
          saveResume(videoId, t);
        }
      } catch {
        // player not ready or destroyed — ignore
      }
    }, [videoId]);

    const handleStateChange = useCallback(
      (event: { data: number }) => {
        if (!window.YT || !videoId) return;
        const state = event.data;
        if (state === window.YT.PlayerState.PLAYING) {
          stopProgressSaver();
          saveIntervalRef.current = setInterval(persistCurrentTime, RESUME_SAVE_INTERVAL_MS);
        } else if (
          state === window.YT.PlayerState.PAUSED ||
          state === window.YT.PlayerState.BUFFERING
        ) {
          stopProgressSaver();
          persistCurrentTime();
        } else if (state === window.YT.PlayerState.ENDED) {
          stopProgressSaver();
          clearResume(videoId);
        }
      },
      [videoId, persistCurrentTime, stopProgressSaver]
    );

    const handleReady = useCallback(() => {
      setIsReady(true);
      const player = playerRef.current;
      if (!player || !videoId) return;
      const saved = loadResume(videoId);
      if (saved === null) return;
      try {
        const duration = player.getDuration?.() ?? 0;
        if (saved >= RESUME_MIN_OFFSET_S && (duration === 0 || saved < duration - RESUME_END_BUFFER_S)) {
          player.seekTo(saved, true);
        }
      } catch {
        // ignore
      }
    }, [videoId]);

    const initPlayer = useCallback(() => {
      if (!videoId || !containerRef.current || playerRef.current) return;

      playerRef.current = new window.YT.Player(containerRef.current, {
        videoId,
        width: '100%',
        height: '100%',
        playerVars: {
          autoplay: 0,
          modestbranding: 1,
          rel: 0,
        },
        events: {
          onReady: handleReady,
          onStateChange: handleStateChange,
        },
      });
    }, [videoId, handleReady, handleStateChange]);

    useEffect(() => {
      pruneOldEntries(RESUME_MAX_AGE_MS);
    }, []);

    useEffect(() => {
      if (window.YT && window.YT.Player) {
        initPlayer();
        return;
      }

      // Load YouTube IFrame API script
      const existingScript = document.querySelector(
        'script[src="https://www.youtube.com/iframe_api"]'
      );
      if (!existingScript) {
        const tag = document.createElement('script');
        tag.src = 'https://www.youtube.com/iframe_api';
        document.head.appendChild(tag);
      }

      window.onYouTubeIframeAPIReady = () => {
        initPlayer();
      };

      return () => {
        window.onYouTubeIframeAPIReady = undefined;
      };
    }, [initPlayer]);

    useEffect(() => {
      const onUnload = () => persistCurrentTime();
      window.addEventListener('beforeunload', onUnload);
      return () => {
        window.removeEventListener('beforeunload', onUnload);
        stopProgressSaver();
        persistCurrentTime();
      };
    }, [persistCurrentTime, stopProgressSaver]);

    const handleSnapshot = async () => {
      if (!playerRef.current || !isReady) return;
      setCapturing(true);
      try {
        const currentTime = playerRef.current.getCurrentTime();
        await onSnapshot(currentTime);
      } finally {
        setCapturing(false);
      }
    };

    if (!videoId) {
      return <div className="text-gray-500">invalid youtube url</div>;
    }

    return (
      <div>
        <div
          className="relative bg-black rounded-lg overflow-hidden mx-auto"
          style={{
            aspectRatio: '16/9',
            width: `${zoom}%`,
          }}
        >
          <div ref={containerRef} className="w-full h-full" />
        </div>
        <button
          onClick={handleSnapshot}
          disabled={disabled || !isReady || capturing}
          className="w-full mt-3 px-4 py-3 text-sm border border-primary text-primary hover:bg-primary hover:text-white rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed font-medium"
        >
          {capturing ? 'capturing...' : 'capture snapshot'}
        </button>
      </div>
    );
  }
);

export default YouTubePlayer;
