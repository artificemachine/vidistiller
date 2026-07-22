'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import apiClient from '@/lib/api';
import { useParams } from 'next/navigation';
import ProcessingStatus from '@/components/ProcessingStatus';
import VideoPlayer from '@/components/VideoPlayer';
import type { VideoPlayerHandle } from '@/components/VideoPlayer';
import SnapshotsGallery from '@/components/SnapshotsGallery';
import SlidesGallery from '@/components/SlidesGallery';
import type { SlideItem } from '@/components/SlidesGallery';
import WorkspaceLayout from '@/components/layout/WorkspaceLayout';
import JobLogs from '@/components/JobLogs';
import type { LogEntry } from '@/components/JobLogs';
import { useJobStatus } from '@/components/JobStatusProvider';
import { parseTimestamp, buildSnapshotMap, toSnakeCase } from '@/lib/utils';
import { exportToObsidian, exportSummaryToObsidian } from '@/lib/exportObsidian';
import OllamaDiagModal from '@/components/OllamaDiagModal';

interface SnapshotItem {
  id: number;
  image_url: string;
  timestamp: number;
  detected_text?: string;
  image_width?: number;
  image_height?: number;
}

interface JobDetail {
  id: number;
  job_id: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  error_message?: string;
  video_url?: string;
  source_type?: string;
  summarize_status?: string | null;
  processing_mode?: string | null;
  created_at: string;
  updated_at: string;
  videos: Array<{
    id: number;
    title: string;
    duration: number;
    description?: string;
  }>;
  transcripts: Array<{
    id: number;
    full_text: string;
    language: string;
  }>;
  documents: Array<{
    id: number;
    title: string;
    content: string;
    format: 'markdown' | 'html' | 'pdf' | 'summary';
  }>;
  snapshots: Array<{
    id: number;
    file_path: string;
    timestamp: number;
    relevance_score: number;
    detected_text?: string;
    image_url?: string;
    image_width?: number;
    image_height?: number;
  }>;
  slides: Array<{
    id: number;
    slide_number: number;
    start_timestamp: number;
    end_timestamp: number;
    image_url?: string;
    ocr_text?: string;
    transcript_text?: string;
    is_incremental_build?: boolean;
    ssim_transition_score?: number;
    image_width?: number;
    image_height?: number;
  }>;
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 768);
    check();
    window.addEventListener('resize', check);
    return () => window.removeEventListener('resize', check);
  }, []);
  return isMobile;
}

export default function JobDetail() {
  const params = useParams();
  const jobId = params.id as string;
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [snapshots, setSnapshots] = useState<SnapshotItem[]>([]);
  const [slides, setSlides] = useState<SlideItem[]>([]);
  const [selectedSnapshotIndex, setSelectedSnapshotIndex] = useState(0);
  const [selectedSlideIndex, setSelectedSlideIndex] = useState(0);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsOpen, setLogsOpen] = useState(true);
  const [showSummary, setShowSummary] = useState(false);

  // Keep logs visible even when job completes
  // useEffect(() => {
  //   if (job && (job.status === 'completed' || job.status === 'failed')) {
  //     setLogsOpen(false);
  //   }
  // }, [job?.status]);
  const [summaryContent, setSummaryContent] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryProgress, setSummaryProgress] = useState(0);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [ollamaDiag, setOllamaDiag] = useState<any | null>(null);
  const playerRef = useRef<VideoPlayerHandle>(null);
  const isMobile = useIsMobile();
  const { setJobStatus } = useJobStatus();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const baseUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/api\/?$/, '');

  // Sync job status to navbar badge; clear on unmount
  useEffect(() => {
    if (job) setJobStatus(job.status);
    return () => setJobStatus(null);
  }, [job?.status, setJobStatus]);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await apiClient.get(`/jobs/${jobId}/logs`);
      setLogs(res.data);
    } catch {
      // logs fetch is best-effort
    }
  }, [jobId]);

  const pollJob = useCallback(async () => {
    try {
      const response = await apiClient.get(`/jobs/${jobId}`);
      setJob(response.data);
      if (response.data.snapshots) {
        setSnapshots(
          response.data.snapshots.map((s: any) => ({
            id: s.id,
            image_url: s.image_url || s.file_path,
            timestamp: s.timestamp,
            detected_text: s.detected_text,
            image_width: s.image_width,
            image_height: s.image_height,
          }))
        );
      }
      if (response.data.slides) {
        setSlides(response.data.slides);
      }
      await fetchLogs();
      // Stop polling only when job is terminal AND no summarization is in flight
      const jobDone = response.data.status === 'completed' || response.data.status === 'failed';
      const summarizeSettled = response.data.summarize_status !== 'processing';
      if (jobDone && summarizeSettled) {
        if (intervalRef.current) {
          clearInterval(intervalRef.current);
          intervalRef.current = null;
        }
      }
    } catch (err: any) {
      console.error('Error polling job status:', err);
    }
  }, [jobId, fetchLogs]);

  useEffect(() => {
    const fetchJob = async () => {
      try {
        const response = await apiClient.get(`/jobs/${jobId}`);
        setJob(response.data);
        if (response.data.snapshots) {
          setSnapshots(
            response.data.snapshots.map((s: any) => ({
              id: s.id,
              image_url: s.image_url || s.file_path,
              timestamp: s.timestamp,
              detected_text: s.detected_text,
            }))
          );
        }
        if (response.data.slides) {
          setSlides(response.data.slides);
        }
        setLoading(false);
        await fetchLogs();
      } catch (err: any) {
        setError(err.response?.data?.message || 'failed to load job details');
        setLoading(false);
      }
    };

    if (!jobId) return;

    fetchJob();
    intervalRef.current = setInterval(pollJob, 5000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [jobId, pollJob, fetchLogs]);

  const handleSnapshot = useCallback(async (timestamp: number) => {
    if (!job) return;
    // Skip if a snapshot already exists within 1 second of this timestamp
    const duplicate = snapshots.some((s) => Math.abs(s.timestamp - timestamp) < 1);
    if (duplicate) return;
    try {
      const response = await apiClient.post(`/snapshots/capture`, {
        job_id: job.job_id,
        timestamp,
      });
      const newSnapshot: SnapshotItem = {
        id: response.data.id,
        image_url: response.data.image_url,
        timestamp: response.data.timestamp,
        detected_text: response.data.detected_text,
        image_width: response.data.image_width,
        image_height: response.data.image_height,
      };
      setSnapshots((prev) => [...prev, newSnapshot]);
      setSelectedSnapshotIndex(-1); // -1 signals "select last"
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'failed to capture snapshot';
      alert(msg);
    }
  }, [job, snapshots]);

  const handleDeleteSnapshot = useCallback(async (snapshotId: number) => {
    try {
      await apiClient.delete(`/snapshots/${snapshotId}`);
      setSnapshots((prev) => prev.filter((s) => s.id !== snapshotId));
    } catch (err: any) {
      console.error('Failed to delete snapshot:', err);
    }
  }, []);

  const handleTimestampClick = useCallback((seconds: number) => {
    playerRef.current?.seekTo(seconds);
  }, []);

  const handlePrintPDF = useCallback(() => {
    window.print();
  }, []);

  const handleExportObsidian = useCallback(async () => {
    if (!job) return;
    const title = job.videos[0]?.title || 'video';
    // Export summary when available, transcript otherwise
    if (summaryContent) {
      await exportSummaryToObsidian({ title, summaryContent, baseUrl });
      return;
    }
    if (job.transcripts.length === 0) return;
    const transcript = job.transcripts[0];
    await exportToObsidian({
      title,
      videoUrl: job.video_url || '',
      transcriptText: transcript.full_text,
      snapshots: snapshots.map((s) => ({ timestamp: s.timestamp, image_url: s.image_url })),
      baseUrl,
      slides: slides.map((s) => ({
        slide_number: s.slide_number,
        start_timestamp: s.start_timestamp,
        end_timestamp: s.end_timestamp,
        image_url: s.image_url,
        ocr_text: s.ocr_text,
        transcript_text: s.transcript_text,
      })),
    });
  }, [job, summaryContent, snapshots, slides, baseUrl]);

  // Auto-load cached summary from job.documents; also detect when background
  // summarization completes (summarize_status transitions to 'completed')
  useEffect(() => {
    if (!job) return;
    const cached = job.documents.find((d) => d.format === 'summary');
    if (cached) {
      setSummaryContent(cached.content);
      if (job.summarize_status === 'completed' && summaryLoading) {
        setSummaryProgress(100);
        setSummaryLoading(false);
        setSummaryError(null);
      }
    }
    if (job.summarize_status === 'failed' && summaryLoading) {
      setSummaryProgress(0);
      setSummaryLoading(false);
      setSummaryError('summarization failed — check that the vLLM fleet is reachable.');
    }
    // If job loaded while summarization is already in progress, show loading/stop
    if (job.summarize_status === 'processing' && !summaryLoading) {
      setSummaryLoading(true);
      setShowSummary(true);
    }
  }, [job?.documents, job?.summarize_status]);

  const handleSummarize = useCallback(async () => {
    if (!job) return;
    // Toggle: if summary is showing, switch back to transcript
    if (showSummary) {
      setShowSummary(false);
      return;
    }
    // If content already loaded, just show it — don't re-generate
    if (summaryContent) {
      setShowSummary(true);
      return;
    }
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      const res = await apiClient.post(`/jobs/${job.job_id}/summarize`);
      if (res.status === 202) {
        // Summarization dispatched as background task; restart polling if it stopped
        setSummaryLoading(true);
        setSummaryError(null);
        setShowSummary(true);
        if (!intervalRef.current) {
          intervalRef.current = setInterval(pollJob, 5000);
        }
      } else {
        setSummaryContent(res.data.content);
        setShowSummary(true);
        setSummaryLoading(false);
      }
    } catch (err: any) {
      const msg = err.response?.data?.message || err.response?.data?.detail || '';
      if (/ollama|connect/i.test(msg)) {
        try {
          const diagRes = await apiClient.get(`/diagnostics/ollama`);
          setOllamaDiag(diagRes.data);
        } catch {
          setOllamaDiag({ error: msg, suggestions: ['could not reach diagnostics endpoint'] });
        }
      } else {
        alert(msg || 'failed to summarize transcript');
      }
      setSummaryLoading(false);
    }
  }, [job, showSummary, pollJob]);

  // Animate progress bar while summarizing; reset on completion/error
  useEffect(() => {
    if (!summaryLoading) return;
    const text = job?.transcripts[0]?.full_text || '';
    const totalSections = Math.max(1, (text.match(/^## \[/gm) || []).length);
    const estimatedMs = totalSections * 4000;
    const start = Date.now();
    const tick = setInterval(() => {
      const elapsed = Date.now() - start;
      setSummaryProgress(Math.min(92, Math.round((elapsed / estimatedMs) * 100)));
    }, 500);
    return () => clearInterval(tick);
  }, [summaryLoading, job?.transcripts]);

  const handleSaveJob = useCallback(async () => {
    if (!job) return;
    try {
      const res = await apiClient.get(`/jobs/${job.job_id}/export`, {
        responseType: 'blob',
      });
      const blob = new Blob([res.data], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const title = job.videos[0]?.title || job.job_id;
      const safeName = toSnakeCase(title);
      a.download = `${safeName}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      alert(err.response?.data?.detail || 'failed to export job');
    }
  }, [job]);

  const handleCancel = useCallback(async () => {
    if (!job) return;
    if (!confirm('are you sure you want to stop the summarization?')) return;
    try {
      await apiClient.post(`/jobs/${job.job_id}/cancel`);
      // Re-fetch job to get updated status
      const response = await apiClient.get(`/jobs/${job.job_id}`);
      setJob(response.data);
    } catch (err: any) {
      alert(err.response?.data?.detail || err.response?.data?.message || 'failed to cancel job');
    }
  }, [job]);

  const handleSlideClick = useCallback((slide: SlideItem) => {
    playerRef.current?.seekTo(slide.start_timestamp);
  }, []);

  if (loading) {
    return (
      <div className="text-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary mx-auto"></div>
        <p className="text-gray-600 dark:text-gray-400 mt-4">loading job details...</p>
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="max-w-4xl mx-auto p-6">
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-6 text-red-700 dark:text-red-400">
          <h2 className="text-lg font-semibold mb-2">error loading job</h2>
          <p>{error || 'job not found'}</p>
        </div>
      </div>
    );
  }

  const renderInlineSnapshots = (snaps: SnapshotItem[]) => (
    <div className="my-2 flex flex-wrap gap-2 px-1">
      {snaps.map((snap) => (
        <div key={snap.id} className="relative rounded overflow-hidden border border-border-light dark:border-border-dark" style={{ width: '160px' }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={`${baseUrl}${snap.image_url}`}
            alt={`snapshot at ${Math.floor(snap.timestamp)}s`}
            className="w-full h-auto block"
          />
          <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] px-1 py-0.5 text-center font-mono">
            {`${Math.floor(snap.timestamp / 3600).toString().padStart(2, '0')}:${Math.floor((snap.timestamp % 3600) / 60).toString().padStart(2, '0')}:${Math.floor(snap.timestamp % 60).toString().padStart(2, '0')}`}
          </span>
        </div>
      ))}
    </div>
  );

  // Render summary markdown: chapter headers, images, paragraphs, bullets
  const renderSummary = (content: string) => {
    const lines = content.split('\n');
    return (
      <div className="p-3 space-y-1">
        {lines.map((line, i) => {
          // Chapter header
          const chapterMatch = line.match(/^## \[(\d{2}:\d{2}:\d{2})\]\s?(.+)/);
          if (chapterMatch) {
            return (
              <div key={i} className="mt-3 mb-1 px-1">
                <h3 className="text-xs font-bold text-gray-900 dark:text-gray-100 border-b border-gray-200 dark:border-gray-700 pb-1">
                  <button
                    onClick={() => handleTimestampClick(parseTimestamp(`[${chapterMatch[1]}]`))}
                    className="hover:text-primary"
                  >
                    [{chapterMatch[1]}] {chapterMatch[2].trim()}
                  </button>
                </h3>
              </div>
            );
          }
          // Snapshot image ref
          const imgMatch = line.match(/^!\[Snapshot at (\d{2}:\d{2}:\d{2})\]\((.+?)\)/);
          if (imgMatch) {
            const imgUrl = imgMatch[2].startsWith('http') ? imgMatch[2] : `${baseUrl}${imgMatch[2]}`;
            return (
              <div key={i} className="my-2 px-1">
                <div className="relative rounded overflow-hidden border border-border-light dark:border-border-dark inline-block" style={{ width: '160px' }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imgUrl}
                    alt={`snapshot at ${imgMatch[1]}`}
                    className="w-full h-auto block"
                  />
                  <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[9px] px-1 py-0.5 text-center font-mono">
                    {imgMatch[1]}
                  </span>
                </div>
              </div>
            );
          }
          // Bullet point
          if (line.match(/^[-*]\s/)) {
            return (
              <div key={i} className="flex gap-1.5 px-2 py-0.5">
                <span className="text-gray-400 text-xs shrink-0">&bull;</span>
                <span className="text-gray-800 dark:text-gray-200 text-xs">{line.replace(/^[-*]\s/, '')}</span>
              </div>
            );
          }
          // Empty line
          if (!line.trim()) return null;
          // Paragraph text
          return (
            <p key={i} className="text-gray-800 dark:text-gray-200 text-xs py-0.5 px-1">{line}</p>
          );
        })}
      </div>
    );
  };

  const showPlayer = job.status === 'completed' && job.video_url;

  // Sidebar content: progress bar, summary, or transcript
  const sidebarSectionCount = (() => {
    const text = job?.transcripts[0]?.full_text || '';
    return Math.max(1, (text.match(/^## \[/gm) || []).length);
  })();
  const sidebarContent =
    showSummary && summaryError
      ? (
        <div className="p-4">
          <p className="text-xs text-red-500 dark:text-red-400">{summaryError}</p>
        </div>
      )
      : showSummary && summaryLoading
        ? (
          <div className="p-4 space-y-3">
            <p className="text-xs text-gray-500 dark:text-gray-400">
              summarizing {sidebarSectionCount} section{sidebarSectionCount !== 1 ? 's' : ''}...
            </p>
            <div className="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all duration-500 ease-out"
                style={{ width: `${summaryProgress}%` }}
              />
            </div>
            <p className="text-[10px] text-gray-400 dark:text-gray-500">
              est. {sidebarSectionCount * 4 >= 60
                ? `${Math.floor(sidebarSectionCount * 4 / 60)}m ${sidebarSectionCount * 4 % 60}s`
                : `${sidebarSectionCount * 4}s`}
            </p>
          </div>
        )
      : showSummary && summaryContent
        ? renderSummary(summaryContent)
        : undefined;

  // Transcript sidebar content
  const transcriptContent = (
    <div className="p-3">
      <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">job: {job.job_id.slice(0, 8)}...</p>
      {job.video_url && (
        <a
          href={job.video_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-primary hover:underline truncate mb-2 px-1"
        >
          {job.video_url}
        </a>
      )}
      {job.transcripts.length > 0 ? (
        job.transcripts.map((t) => {
          const lines = t.full_text.split('\n');
          const snapMap = buildSnapshotMap(lines, snapshots);
          return (
            <div key={t.id} className="mb-4">
              <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">language: {t.language}</p>
              <div className="space-y-0.5">
                {lines.map((line, i) => {
                  const inlineSnaps = snapMap.get(i);

                  // Check for chapter header: ## [HH:MM:SS] Title
                  const chapterMatch = line.match(/^## \[(\d{2}:\d{2}:\d{2})\]\s?(.+)/);
                  if (chapterMatch) {
                    return (
                      <div key={i}>
                        <div className="mt-3 mb-1 px-1">
                          <h3 className="text-xs font-bold text-gray-900 dark:text-gray-100 border-b border-gray-200 dark:border-gray-700 pb-1">
                            <button
                              onClick={() => handleTimestampClick(parseTimestamp(`[${chapterMatch[1]}]`))}
                              className="hover:text-blue-600 dark:hover:text-blue-400"
                            >
                              [{chapterMatch[1]}] {chapterMatch[2].trim()}
                            </button>
                          </h3>
                        </div>
                        {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                      </div>
                    );
                  }

                  const match = line.match(/^(\[\d{2}:\d{2}:\d{2}\])\s?(.*)/);
                  if (match) {
                    const seconds = parseTimestamp(match[1]);
                    return (
                      <div key={i}>
                        <div className="flex gap-2 py-0.5 hover:bg-border-light dark:hover:bg-border-dark/20 rounded px-1 group">
                          <button
                            onClick={() => handleTimestampClick(seconds)}
                            className="text-gray-400 dark:text-gray-500 hover:text-primary hover:underline font-mono text-xs whitespace-nowrap shrink-0 transition-colors"
                          >
                            {match[1]}
                          </button>
                          <span className="text-gray-800 dark:text-gray-200 text-xs">{match[2]}</span>
                        </div>
                        {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                      </div>
                    );
                  }
                  if (!line.trim()) return null;
                  return (
                    <div key={i}>
                      <p className="text-gray-800 dark:text-gray-200 text-xs py-0.5 px-1">{line}</p>
                      {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })
      ) : (
        <p className="text-gray-500 dark:text-gray-400 text-sm">no transcript available yet.</p>
      )}
    </div>
  );

  // Main player content (receives zoom level from WorkspaceLayout)
  const playerContent = (zoom: number) => showPlayer ? (
    <VideoPlayer
      ref={playerRef}
      videoUrl={job.video_url!}
      onSnapshot={handleSnapshot}
      zoom={zoom}
    />
  ) : (
    <div className="flex flex-col items-center justify-center h-full text-gray-500 dark:text-gray-400">
      <ProcessingStatus
        status={job.status}
        progress={job.status === 'completed' ? 100 : job.status === 'processing' ? 50 : 0}
        message={
          job.error_message
            ? `error: ${job.error_message}`
            : job.status === 'completed'
              ? 'processing complete!'
              : job.status === 'processing'
                ? 'processing your video...'
                : 'waiting to start processing'
        }
      />
    </div>
  );

  const showLogs = logs.length > 0 || job.status === 'pending' || job.status === 'processing';

  // Logs panel content (rendered inside its own resizable panel)
  const logsContent = showLogs ? (
    <div className="bg-gray-900 h-full p-3 font-mono text-xs leading-relaxed overflow-y-auto">
      {logs.length === 0 ? (
        <p className="text-gray-500">no logs yet...</p>
      ) : (
        logs.map((log) => (
          <div key={log.id} className="flex gap-2 py-0.5">
            <span className="text-gray-500 whitespace-nowrap shrink-0">
              {new Date(log.created_at).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
            <span className={`whitespace-nowrap shrink-0 ${log.level === 'error' ? 'text-red-400' : log.level === 'warning' ? 'text-yellow-400' : 'text-green-400'}`}>
              [{log.level === 'error' ? 'ERROR' : log.level === 'warning' ? 'WARN' : 'INFO'}]
            </span>
            {log.step && (
              <span className="text-gray-500 whitespace-nowrap shrink-0">{log.step}:</span>
            )}
            <span className="text-gray-200">{log.message}</span>
          </div>
        ))
      )}
    </div>
  ) : null;

  const formatSlideTime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  // Bottom panel content — hide ProcessingStatus when complete (status shown in navbar)
  const isSlideMode = job.processing_mode === 'slide_aware' && slides.length > 0;
  const bottomContent = (
    <div>
      {job.status !== 'completed' && (
        <div className="mb-4">
          <ProcessingStatus
            status={job.status}
            progress={job.status === 'processing' ? 50 : 0}
            message={
              job.error_message
                ? `error: ${job.error_message}`
                : job.status === 'processing'
                  ? 'processing your video...'
                  : 'waiting to start processing'
            }
          />
        </div>
      )}
      {isSlideMode ? (
        <SlidesGallery
          slides={slides}
          onSlideClick={handleSlideClick}
          externalSelectedIndex={selectedSlideIndex}
          onSelectedIndexChange={setSelectedSlideIndex}
        />
      ) : (
        <SnapshotsGallery
          snapshots={snapshots}
          onDelete={handleDeleteSnapshot}
          externalSelectedIndex={selectedSnapshotIndex}
          onSelectedIndexChange={setSelectedSnapshotIndex}
        />
      )}
    </div>
  );

  const currentSlide = isSlideMode && slides.length > 0
    ? slides[Math.min(Math.max(selectedSlideIndex, 0), slides.length - 1)]
    : null;

  const slideTextContent = currentSlide ? (
    <div className="p-3 space-y-3">
      <p className="text-xs text-gray-500 dark:text-gray-400 font-mono">
        slide {currentSlide.slide_number} · {formatSlideTime(currentSlide.start_timestamp)} – {formatSlideTime(currentSlide.end_timestamp)}
      </p>
      {currentSlide.ocr_text && (
        <div>
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">ocr text</p>
          <p className="text-xs text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{currentSlide.ocr_text}</p>
        </div>
      )}
      {currentSlide.transcript_text && (
        <div>
          <p className="text-xs font-semibold text-blue-600 dark:text-blue-400 mb-1">transcript</p>
          <p className="text-xs text-gray-700 dark:text-gray-300">{currentSlide.transcript_text}</p>
        </div>
      )}
      {!currentSlide.ocr_text && !currentSlide.transcript_text && (
        <p className="text-xs text-gray-400">no text content available for this slide.</p>
      )}
    </div>
  ) : null;

  // Ollama diagnostics modal
  const diagModal = ollamaDiag && (
    <OllamaDiagModal diag={ollamaDiag} onDismiss={() => setOllamaDiag(null)} />
  );

  // Mobile: stacked layout (original design)
  if (isMobile) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-6">
        {diagModal}
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-50 mb-1">job details</h1>
          <p className="text-gray-600 dark:text-gray-400 text-sm">job id: {job.job_id}</p>
        </div>

        <div className="mb-6">
          <ProcessingStatus
            status={job.status}
            progress={job.status === 'completed' ? 100 : job.status === 'processing' ? 50 : 0}
            message={
              job.error_message
                ? `error: ${job.error_message}`
                : job.status === 'completed'
                  ? 'processing complete!'
                  : job.status === 'processing'
                    ? 'processing your video...'
                    : 'waiting to start processing'
            }
          />
        </div>

        {showLogs && (
          <div className="mb-6">
            <JobLogs logs={logs} isOpen={logsOpen} onToggle={() => setLogsOpen((v) => !v)} />
          </div>
        )}

        {showPlayer && (
          <>
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900 p-4 mb-6">
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-3">video player</h2>
              <VideoPlayer
                videoUrl={job.video_url!}
                onSnapshot={handleSnapshot}
              />
            </div>
            <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900 p-4 mb-6">
              <SnapshotsGallery
                snapshots={snapshots}
                onDelete={handleDeleteSnapshot}
              />
            </div>
          </>
        )}

        {job.transcripts.length > 0 && (
          <div className="bg-white dark:bg-gray-900 rounded-lg shadow dark:shadow-gray-900 p-4 mb-6">
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-50 mb-3">transcript</h2>
            {job.transcripts.map((t) => {
              const mobileLines = t.full_text.split('\n');
              const mobileSnapMap = buildSnapshotMap(mobileLines, snapshots);
              return (
                <div key={t.id} className="mb-4">
                  <p className="text-sm text-gray-600 dark:text-gray-400 mb-2">language: {t.language}</p>
                  <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 max-h-[400px] overflow-y-auto">
                    {mobileLines.map((line, i) => {
                      const inlineSnaps = mobileSnapMap.get(i);

                      // Check for chapter header: ## [HH:MM:SS] Title
                      const chapterMatch = line.match(/^## \[(\d{2}:\d{2}:\d{2})\]\s?(.+)/);
                      if (chapterMatch) {
                        return (
                          <div key={i}>
                            <div className="mt-3 mb-1 px-2">
                              <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 border-b border-gray-200 dark:border-gray-700 pb-1">
                                [{chapterMatch[1]}] {chapterMatch[2].trim()}
                              </h3>
                            </div>
                            {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                          </div>
                        );
                      }
                      const match = line.match(/^(\[\d{2}:\d{2}:\d{2}\])\s?(.*)/);
                      if (match) {
                        return (
                          <div key={i}>
                            <div className="flex gap-3 py-1 hover:bg-border-light dark:hover:bg-border-dark/30 rounded px-2">
                              <span className="text-primary font-mono font-medium text-sm whitespace-nowrap">{match[1]}</span>
                              <span className="text-gray-800 dark:text-gray-200 text-sm">{match[2]}</span>
                            </div>
                            {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                          </div>
                        );
                      }
                      if (!line.trim()) return null;
                      return (
                        <div key={i}>
                          <p className="text-gray-800 dark:text-gray-200 text-sm py-1">{line}</p>
                          {inlineSnaps && renderInlineSnapshots(inlineSnaps)}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {job.status === 'pending' && (
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6 text-center">
            <p className="text-yellow-800 dark:text-yellow-400">
              processing hasn&apos;t started yet. check back in a few moments.
            </p>
          </div>
        )}
      </div>
    );
  }

  const sidebarActions = (
    <div className="flex items-center gap-1.5">
      {job.transcripts.length > 0 && (
        <>
          {summaryLoading && (
            <button
              onClick={async () => {
                try { await apiClient.post(`/jobs/${job.job_id}/cancel`); } catch {}
                setSummaryLoading(false);
              }}
              className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
              title="stop summarization"
            >
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" />
              </svg>
              stop
            </button>
          )}
          <button
            onClick={handleSummarize}
            disabled={summaryLoading}
            className={`flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${showSummary ? 'bg-info/20 text-info' : 'bg-border-light text-text-dark hover:bg-border-light/80 dark:bg-border-dark dark:text-text-light dark:hover:bg-border-dark/80'}`}
          >
            {summaryLoading ? (
              <svg className="animate-spin" width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="7" cy="7" r="5.5" stroke="currentColor" strokeWidth="1.5" strokeDasharray="20 10" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 5l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            {summaryLoading ? 'summarizing...' : showSummary ? 'transcript' : 'summary'}
          </button>
          <button
            onClick={handleExportObsidian}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-border-light text-text-dark hover:bg-border-light/80 dark:bg-border-dark dark:text-text-light dark:hover:bg-border-dark/80 transition-colors"
            title="Export to Markdown ZIP"
          >
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M7 1v8M7 9L4 6M7 9l3-3M2 11h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            markdown
          </button>
          <button
            onClick={handlePrintPDF}
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-border-light text-text-dark hover:bg-border-light/80 dark:bg-border-dark dark:text-text-light dark:hover:bg-border-dark/80 transition-colors"
            title="Print / Save as PDF"
          >
            <svg width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M3 5V2h8v3M3 10H1V5h12v5h-2M3 8h8v4H3z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            pdf
          </button>
        </>
      )}
      <button
        onClick={handleSaveJob}
        className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-border-light text-text-dark hover:bg-border-light/80 dark:bg-border-dark dark:text-text-light dark:hover:bg-border-dark/80 transition-colors"
        title="Download job data as JSON backup"
      >
        <svg width="12" height="12" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M11 13H3a1 1 0 01-1-1V2a1 1 0 011-1h6l3 3v8a1 1 0 01-1 1z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M9 1v3h3M5 9h4M5 11h2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        backup
      </button>
    </div>
  );

  const printLines = (() => {
    if (showSummary && summaryContent) return null;
    const raw = job?.transcripts[0]?.full_text || '';
    const firstTs = raw.search(/\[\d{2}:\d{2}:\d{2}\]/);
    return (firstTs >= 0 ? raw.slice(firstTs) : raw).split('\n');
  })();

  // Desktop: VS Code-like panel layout
  return (
    <>
    {diagModal}

    {/* Print-only view: matches sidebar rendering — bold timestamps, spaced lines */}
    <div className="hidden print:block p-8 max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">{job?.videos[0]?.title ?? 'transcript'}</h1>
      <p className="text-xs text-gray-400 mb-6">{job?.video_url}</p>
      {showSummary && summaryContent ? (
        <div className="whitespace-pre-wrap text-sm leading-relaxed">{summaryContent}</div>
      ) : printLines ? (
        <div className="text-sm leading-loose">
          {printLines.map((line, i) => {
            const chapter = line.match(/^## \[(\d{2}:\d{2}:\d{2})\]\s?(.+)/);
            if (chapter) return (
              <div key={i} className="mt-4 mb-1 font-bold border-b border-gray-300 pb-0.5">
                [{chapter[1]}] {chapter[2].trim()}
              </div>
            );
            const ts = line.match(/^(\[\d{2}:\d{2}:\d{2}\])\s?(.*)/);
            if (ts) return (
              <div key={i} className="flex gap-3 py-0.5">
                <span className="font-mono font-bold text-gray-600 shrink-0">{ts[1]}</span>
                <span>{ts[2]}</span>
              </div>
            );
            if (!line.trim()) return null;
            return <p key={i} className="py-0.5 text-gray-500">{line}</p>;
          })}
        </div>
      ) : null}
    </div>

    <div className="h-full print:hidden">
      <WorkspaceLayout
        sidebar={sidebarContent ?? transcriptContent}
        main={playerContent}
        logs={bottomContent}
        logsCollapsed={!logsOpen}
        bottom={logsContent ?? undefined}
        sidebarActions={sidebarActions}
        sidebarTitle={showSummary ? 'summary' : 'transcript'}
        slideText={isSlideMode ? slideTextContent : undefined}
      />
    </div>
    </>
  );
}
