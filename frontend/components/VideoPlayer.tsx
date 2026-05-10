'use client';

import { useRef, useState, useEffect, useCallback, useImperativeHandle, forwardRef } from 'react';
import ReactPlayer from 'react-player';
import { loadResume, saveResume, clearResume, pruneOldEntries } from '@/lib/videoResume';

const RESUME_SAVE_INTERVAL_MS = 5000;
const RESUME_MIN_OFFSET_S = 5;
const RESUME_END_BUFFER_S = 5;
const RESUME_MAX_AGE_MS = 90 * 24 * 3600 * 1000;

interface VideoPlayerProps {
  videoUrl: string;
  onSnapshot: (timestamp: number) => void;
  disabled?: boolean;
  zoom?: number;
}

export interface VideoPlayerHandle {
  seekTo: (seconds: number) => void;
  getCurrentTime: () => number;
}

// react-player v3 exposes a native HTMLVideoElement ref
const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(
  function VideoPlayer({ videoUrl, onSnapshot, disabled, zoom = 100 }, ref) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [isReady, setIsReady] = useState(false);
    const [capturing, setCapturing] = useState(false);
    const saveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useImperativeHandle(ref, () => ({
      seekTo: (seconds: number) => {
        if (videoRef.current) videoRef.current.currentTime = seconds;
      },
      getCurrentTime: () => videoRef.current?.currentTime ?? 0,
    }), []);

    const stopProgressSaver = useCallback(() => {
      if (saveIntervalRef.current) {
        clearInterval(saveIntervalRef.current);
        saveIntervalRef.current = null;
      }
    }, []);

    const persistCurrentTime = useCallback(() => {
      const el = videoRef.current;
      if (!el || !videoUrl) return;
      const t = el.currentTime;
      const duration = el.duration;
      if (isFinite(duration) && duration > 0 && t >= duration - RESUME_END_BUFFER_S) {
        clearResume(videoUrl);
        return;
      }
      if (t >= RESUME_MIN_OFFSET_S) {
        saveResume(videoUrl, t);
      }
    }, [videoUrl]);

    useEffect(() => {
      pruneOldEntries(RESUME_MAX_AGE_MS);
    }, []);

    const handleReady = useCallback(() => {
      setIsReady(true);
      const el = videoRef.current;
      if (!el || !videoUrl) return;
      const saved = loadResume(videoUrl);
      if (saved === null) return;
      setTimeout(() => {
        if (!el) return;
        const duration = el.duration;
        if (saved >= RESUME_MIN_OFFSET_S && (!isFinite(duration) || duration === 0 || saved < duration - RESUME_END_BUFFER_S)) {
          el.currentTime = saved;
        }
      }, 100);
    }, [videoUrl]);

    const handlePlay = useCallback(() => {
      stopProgressSaver();
      saveIntervalRef.current = setInterval(persistCurrentTime, RESUME_SAVE_INTERVAL_MS);
    }, [persistCurrentTime, stopProgressSaver]);

    const handlePause = useCallback(() => {
      stopProgressSaver();
      persistCurrentTime();
    }, [persistCurrentTime, stopProgressSaver]);

    const handleEnded = useCallback(() => {
      stopProgressSaver();
      clearResume(videoUrl);
    }, [videoUrl, stopProgressSaver]);

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
      if (!isReady || !videoRef.current) return;
      setCapturing(true);
      try {
        await onSnapshot(videoRef.current.currentTime);
      } finally {
        setCapturing(false);
      }
    };

    return (
      <div>
        <div
          className="relative bg-black rounded-lg overflow-hidden mx-auto"
          style={{ aspectRatio: '16/9', width: `${zoom}%` }}
        >
          <ReactPlayer
            ref={videoRef}
            src={videoUrl}
            controls
            width="100%"
            height="100%"
            onReady={handleReady}
            onPlay={handlePlay}
            onPause={handlePause}
            onEnded={handleEnded}
          />
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

export default VideoPlayer;
