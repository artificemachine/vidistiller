'use client';

import { useEffect, useRef, useState, useCallback, useImperativeHandle, forwardRef } from 'react';

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
          onReady: () => setIsReady(true),
        },
      });
    }, [videoId]);

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
