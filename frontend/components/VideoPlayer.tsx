'use client';

import { useRef, useState, useImperativeHandle, forwardRef } from 'react';
import ReactPlayer from 'react-player';

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

    useImperativeHandle(ref, () => ({
      seekTo: (seconds: number) => {
        if (videoRef.current) videoRef.current.currentTime = seconds;
      },
      getCurrentTime: () => videoRef.current?.currentTime ?? 0,
    }), []);

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
            onReady={() => setIsReady(true)}
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
