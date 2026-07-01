import { useState, useEffect, useRef } from 'react';
import {
  Mic,
  Loader2,
  ChevronDown,
  ChevronUp,
  ZoomIn,
  AlignLeft,
  Download,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Play,
  Clock,
} from 'lucide-react';
import { podcastService } from '../../services/podcast';
import { projectService } from '../../services/projects';
import { triggerDownload } from '../../lib/utils';
import type {
  PodcastAnalyzeRequest,
  CaptionSegment,
  ImportantMoment,
  ZoomEffect,
  PodcastTimeline,
} from '../../services/podcast';

type PodcastStep =
  | 'configure'   // Settings + start button
  | 'processing'  // Polling for job completion
  | 'results'     // Show transcript, captions, zoom markers, final video
  | 'failed';

const processingMessages = [
  'Extracting audio from your video…',
  'Loading Whisper model…',
  'Transcribing every word…',
  'Detecting speech patterns…',
  'Building word timestamps…',
  'Grouping into caption lines…',
  'Sending transcript to AI…',
  'Finding your key moments…',
  'Calculating zoom keyframes…',
  'Rendering captions onto video…',
  'Applying zoom effects…',
  'Encoding final output…',
  'Almost done…',
];

const intensityColor: Record<string, string> = {
  high: 'bg-orange-500 text-white',
  medium: 'bg-orange-200 text-orange-800',
  low: 'bg-surface-200 text-surface-600',
};

const reasonLabel: Record<string, string> = {
  key_insight: '💡 Key Insight',
  statistics: '📊 Statistics',
  strong_opinion: '🔥 Strong Opinion',
  emotional_peak: '❤️ Emotional Peak',
  conclusion: '✅ Conclusion',
  story_climax: '🎭 Story Climax',
  call_to_action: '📣 Call to Action',
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

interface Props {
  projectId: string;
  mediaAssets: any[];
}

export default function PodcastPhase({ projectId, mediaAssets }: Props) {
  const [step, setStep] = useState<PodcastStep>('configure');
  const [job, setJob] = useState<any>(null);
  const [timeline, setTimeline] = useState<PodcastTimeline | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [msgIdx, setMsgIdx] = useState(0);
  const [showTranscript, setShowTranscript] = useState(false);
  const [showCaptions, setShowCaptions] = useState(true);
  const [showMoments, setShowMoments] = useState(true);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // On mount — check if project already has a completed podcast job
  useEffect(() => {
    podcastService.getTimeline(projectId)
      .then(tl => {
        setTimeline(tl);
        setStep('results');
      })
      .catch(() => {
        // No completed job yet — stay on configure
      });
  }, [projectId]);

  // Options
  const [captionStyle] = useState<PodcastAnalyzeRequest['caption_style']>('line_by_line');
  const [wordsPerLine, setWordsPerLine] = useState(4);
  const [zoomIntensity, setZoomIntensity] = useState(1.2);
  const [captionPosition, setCaptionPosition] =
    useState<PodcastAnalyzeRequest['caption_position']>('bottom');

  // Cycle processing messages
  useEffect(() => {
    if (step !== 'processing') return;
    const id = setInterval(
      () => setMsgIdx(i => (i + 1) % processingMessages.length),
      2800
    );
    return () => clearInterval(id);
  }, [step]);

  // Poll job status during processing
  useEffect(() => {
    if (step !== 'processing' || !job?.id) return;

    pollingRef.current = setInterval(async () => {
      try {
        const updated = await projectService.getJobStatus(job.id);
        setJob(updated);

        if (updated.status === 'COMPLETED') {
          clearInterval(pollingRef.current!);
          // Fetch podcast timeline
          try {
            const tl = await podcastService.getTimeline(projectId);
            setTimeline(tl);
          } catch {
            // timeline might not be ready — try once more after a short delay
            setTimeout(async () => {
              try {
                const tl = await podcastService.getTimeline(projectId);
                setTimeline(tl);
              } catch {
                /* best effort */
              }
            }, 2000);
          }          setStep('results');
        } else if (updated.status === 'FAILED') {
          clearInterval(pollingRef.current!);
          setErrorMsg(updated.error_message || 'Processing failed. Please try again.');
          setStep('failed');
        }
      } catch (e) {
        console.error('Podcast polling error:', e);
      }
    }, 3000);

    return () => clearInterval(pollingRef.current!);
  }, [step, job?.id, projectId]);

  const handleStart = async () => {
    if (mediaAssets.length === 0) {
      setErrorMsg('Upload a talking-head video first.');
      return;
    }
    if (mediaAssets.length > 1) {
      setErrorMsg('Podcast mode works with one video at a time. Please remove extra files.');
      return;
    }

    setErrorMsg(null);
    setStep('processing');
    setMsgIdx(0);

    try {
      const newJob = await podcastService.startProcessing(projectId, {
        caption_style: captionStyle,
        words_per_line: wordsPerLine,
        zoom_detection: 'auto_llm',
        zoom_intensity: zoomIntensity,
        caption_position: captionPosition,
        font_size: 48,
        font_color: 'white',
      });
      setJob(newJob);
    } catch (err: any) {
      setErrorMsg(err.userMessage || 'Failed to start processing.');
      setStep('failed');
    }
  };

  // ── CONFIGURE ────────────────────────────────────────────────────────────────
  if (step === 'configure') {
    return (
      <div className="flex-1 overflow-y-auto custom-scroll px-5 pb-6">
        <div className="max-w-xl mx-auto space-y-4 pt-2">

          {/* Header bubble */}
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-orange-500 flex items-center justify-center flex-shrink-0 shadow-sm mt-0.5">
              <Mic className="w-4 h-4 text-white" />
            </div>
            <div className="bg-white rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm border border-surface-100 flex-1">
              <p className="text-sm font-semibold text-surface-900">Ready to turn your talking-head video into a viral clip?</p>
              <p className="text-xs text-surface-500 mt-1 leading-relaxed">
                Whisper will transcribe every word → AI finds key moments → auto-zoom + captions burned in.
              </p>
            </div>
          </div>

          {/* Check: single video */}
          {mediaAssets.length === 0 && (
            <div className="flex items-center gap-2.5 px-4 py-3 bg-orange-50 border border-orange-200 rounded-xl">
              <AlertCircle className="w-4 h-4 text-orange-500 flex-shrink-0" />
              <p className="text-xs font-medium text-orange-700">Upload a single talking-head video above first.</p>
            </div>
          )}
          {mediaAssets.length > 1 && (
            <div className="flex items-center gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl">
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
              <p className="text-xs font-medium text-red-700">Podcast mode supports one video at a time. Remove extra files.</p>
            </div>
          )}
          {mediaAssets.length === 1 && (
            <div className="flex items-center gap-2.5 px-4 py-3 bg-green-50 border border-green-200 rounded-xl">
              <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0" />
              <p className="text-xs font-medium text-green-700">1 video ready — {mediaAssets[0].filename}</p>
            </div>
          )}

          {/* Settings card */}
          <div className="bg-white rounded-2xl border border-surface-100 shadow-sm divide-y divide-surface-100">

            {/* Words per line */}
            <div className="px-4 py-3 flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-surface-800 flex items-center gap-1.5">
                  <AlignLeft className="w-3.5 h-3.5 text-orange-500" />
                  Words per caption line
                </p>
                <p className="text-xs text-surface-400 mt-0.5">3–5 words, CapCut style</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setWordsPerLine(w => Math.max(2, w - 1))}
                  className="w-7 h-7 rounded-full bg-surface-100 hover:bg-surface-200 flex items-center justify-center text-surface-700 font-bold transition-colors cursor-pointer"
                >−</button>
                <span className="w-5 text-center text-sm font-bold text-surface-900">{wordsPerLine}</span>
                <button
                  onClick={() => setWordsPerLine(w => Math.min(6, w + 1))}
                  className="w-7 h-7 rounded-full bg-surface-100 hover:bg-surface-200 flex items-center justify-center text-surface-700 font-bold transition-colors cursor-pointer"
                >+</button>
              </div>
            </div>

            {/* Zoom intensity */}
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <p className="text-sm font-semibold text-surface-800 flex items-center gap-1.5">
                    <ZoomIn className="w-3.5 h-3.5 text-orange-500" />
                    Zoom intensity
                  </p>
                  <p className="text-xs text-surface-400 mt-0.5">How much to punch in on key moments</p>
                </div>
                <span className="text-sm font-bold text-orange-500">{zoomIntensity.toFixed(1)}×</span>
              </div>
              <input
                type="range"
                min={1.1}
                max={1.3}
                step={0.05}
                value={zoomIntensity}
                onChange={e => setZoomIntensity(parseFloat(e.target.value))}
                className="w-full accent-orange-500 cursor-pointer"
              />
              <div className="flex justify-between text-[10px] text-surface-400 mt-1">
                <span>Subtle 1.1×</span>
                <span>Moderate 1.3×</span>
              </div>
            </div>

            {/* Caption position */}
            <div className="px-4 py-3">
              <p className="text-sm font-semibold text-surface-800 mb-2">Caption position</p>
              <div className="flex gap-2">
                {(['bottom', 'center', 'top'] as const).map(pos => (
                  <button
                    key={pos}
                    onClick={() => setCaptionPosition(pos)}
                    className={`flex-1 py-2 rounded-xl text-xs font-semibold border transition-all cursor-pointer capitalize ${
                      captionPosition === pos
                        ? 'bg-orange-500 text-white border-orange-500 shadow-sm'
                        : 'bg-surface-50 text-surface-600 border-surface-200 hover:border-orange-300'
                    }`}
                  >
                    {pos}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Free stack note */}
          <div className="flex items-center gap-2 px-4 py-2.5 bg-surface-50 border border-surface-100 rounded-xl">
            <Sparkles className="w-3.5 h-3.5 text-orange-400 flex-shrink-0" />
            <p className="text-[11px] text-surface-500">
              <span className="font-semibold text-surface-700">Completely free</span> — Whisper runs locally, LLM uses free OpenRouter models, FFmpeg renders. ₹0 per video.
            </p>
          </div>

          {errorMsg && (
            <div className="flex items-center gap-2.5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl">
              <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
              <p className="text-xs font-medium text-red-700">{errorMsg}</p>
            </div>
          )}

          {/* Start button */}
          <button
            onClick={handleStart}
            disabled={mediaAssets.length !== 1}
            className="w-full py-3.5 rounded-2xl bg-orange-500 hover:bg-orange-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold text-sm flex items-center justify-center gap-2 shadow-lg shadow-orange-500/25 active:scale-[0.98] transition-all cursor-pointer"
          >
            <Mic className="w-4 h-4" />
            Start Podcast Processing
          </button>
        </div>
      </div>
    );
  }

  // ── PROCESSING ────────────────────────────────────────────────────────────────
  if (step === 'processing') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 gap-6">
        {/* Animated mic */}
        <div className="relative">
          <div className="w-20 h-20 rounded-full bg-orange-100 flex items-center justify-center">
            <div className="absolute inset-0 rounded-full bg-orange-200 animate-ping opacity-40" />
            <Mic className="w-9 h-9 text-orange-500 relative z-10" />
          </div>
        </div>

        {/* Message */}
        <div className="text-center max-w-xs">
          <p className="text-base font-semibold text-surface-900 animate-fade-in" key={msgIdx}>
            {processingMessages[msgIdx]}
          </p>
          <p className="text-xs text-surface-400 mt-2">This takes 45–90 seconds for a 1-minute video</p>
        </div>

        {/* Pipeline steps */}
        <div className="w-full max-w-sm space-y-2">
          {[
            { icon: '🎵', label: 'Extract audio' },
            { icon: '🗣️', label: 'Whisper transcription' },
            { icon: '📝', label: 'Generate captions' },
            { icon: '🧠', label: 'AI detects key moments' },
            { icon: '🔍', label: 'Calculate zoom effects' },
            { icon: '🎬', label: 'Render final video' },
          ].map((s, i) => (
            <div key={s.label} className="flex items-center gap-3 px-4 py-2.5 bg-white rounded-xl border border-surface-100">
              <span className="text-base">{s.icon}</span>
              <span className="text-xs font-medium text-surface-700 flex-1">{s.label}</span>
              <Loader2 className="w-3.5 h-3.5 text-orange-400 animate-spin opacity-70" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── FAILED ────────────────────────────────────────────────────────────────────
  if (step === 'failed') {
    return (
      <div className="flex-1 flex flex-col items-center justify-center px-6 gap-4 text-center">
        <div className="w-16 h-16 rounded-full bg-red-50 flex items-center justify-center">
          <AlertCircle className="w-8 h-8 text-red-500" />
        </div>
        <div>
          <p className="font-semibold text-surface-900 text-base">Processing failed</p>
          <p className="text-xs text-surface-500 mt-1 max-w-xs leading-relaxed">
            {errorMsg || 'Something went wrong. Make sure Whisper is installed and the video has clear audio.'}
          </p>
        </div>
        <button
          onClick={() => { setStep('configure'); setErrorMsg(null); }}
          className="px-6 py-2.5 bg-orange-500 hover:bg-orange-600 text-white rounded-xl font-semibold text-sm transition-colors cursor-pointer"
        >
          Try again
        </button>
      </div>
    );
  }

  // ── RESULTS ────────────────────────────────────────────────────────────────────
  const finalVideoUrl = timeline?.final_video_url || null;

  return (
    <div className="flex-1 overflow-y-auto custom-scroll px-5 pb-8">
      <div className="max-w-xl mx-auto space-y-4 pt-2">

        {/* Success header */}
        <div className="flex items-center gap-3 px-4 py-3 bg-green-50 border border-green-200 rounded-2xl">
          <CheckCircle2 className="w-5 h-5 text-green-500 flex-shrink-0" />
          <div>
            <p className="text-sm font-semibold text-green-800">Podcast video ready!</p>
            <p className="text-xs text-green-600">Captions + zoom effects applied</p>
          </div>
        </div>

        {/* Final video player */}
        {finalVideoUrl ? (
          <div className="bg-black rounded-2xl overflow-hidden shadow-lg">
            <video
              src={finalVideoUrl}
              controls
              playsInline
              className="w-full max-h-[400px] object-contain"
            />
            <div className="px-4 py-3 flex items-center justify-between bg-surface-900">
              <p className="text-xs font-medium text-white/70">Final video with captions + auto-zoom</p>
              <button
                onClick={() => triggerDownload(finalVideoUrl)}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-orange-500 hover:bg-orange-600 text-white rounded-lg text-xs font-semibold transition-colors cursor-pointer"
              >
                <Download className="w-3.5 h-3.5" />
                Download
              </button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 px-4 py-3 bg-surface-100 border border-surface-200 rounded-2xl">
            <Loader2 className="w-4 h-4 animate-spin text-orange-400" />
            <p className="text-xs text-surface-600">Final video URL loading…</p>
          </div>
        )}

        {/* Important moments */}
        {timeline && timeline.important_moments.length > 0 && (
          <div className="bg-white rounded-2xl border border-surface-100 shadow-sm overflow-hidden">
            <button
              onClick={() => setShowMoments(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-50 transition-colors cursor-pointer"
            >
              <span className="text-sm font-semibold text-surface-900 flex items-center gap-2">
                <ZoomIn className="w-4 h-4 text-orange-500" />
                Zoom moments ({timeline.important_moments.length} detected)
              </span>
              {showMoments ? <ChevronUp className="w-4 h-4 text-surface-400" /> : <ChevronDown className="w-4 h-4 text-surface-400" />}
            </button>

            {showMoments && (
              <div className="divide-y divide-surface-50">
                {timeline.important_moments.map((moment: ImportantMoment, i: number) => (
                  <div key={i} className="px-4 py-3 flex items-start gap-3">
                    <div className="flex flex-col items-center gap-1 flex-shrink-0">
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${intensityColor[moment.intensity]}`}>
                        {moment.intensity}
                      </span>
                      <span className="text-[10px] text-surface-400 font-mono flex items-center gap-0.5">
                        <Clock className="w-2.5 h-2.5" />
                        {formatTime(moment.start_time)}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-surface-800 leading-relaxed">"{moment.text}"</p>
                      <p className="text-[10px] text-surface-400 mt-1">
                        {reasonLabel[moment.reason] || moment.reason}
                        {' · '}zoom {formatTime(moment.start_time)}–{formatTime(moment.end_time)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Caption segments */}
        {timeline && timeline.caption_segments.length > 0 && (
          <div className="bg-white rounded-2xl border border-surface-100 shadow-sm overflow-hidden">
            <button
              onClick={() => setShowCaptions(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-50 transition-colors cursor-pointer"
            >
              <span className="text-sm font-semibold text-surface-900 flex items-center gap-2">
                <AlignLeft className="w-4 h-4 text-orange-500" />
                Captions ({timeline.caption_segments.length} lines)
              </span>
              {showCaptions ? <ChevronUp className="w-4 h-4 text-surface-400" /> : <ChevronDown className="w-4 h-4 text-surface-400" />}
            </button>

            {showCaptions && (
              <div className="max-h-64 overflow-y-auto custom-scroll divide-y divide-surface-50">
                {timeline.caption_segments.map((seg: CaptionSegment, i: number) => (
                  <div key={i} className="px-4 py-2 flex items-center gap-3">
                    <span className="text-[10px] text-surface-400 font-mono w-10 flex-shrink-0">
                      {formatTime(seg.start_time)}
                    </span>
                    <span className="text-xs text-surface-800 font-medium">{seg.text}</span>
                    <span className="text-[10px] text-surface-300 ml-auto flex-shrink-0">
                      {seg.duration.toFixed(1)}s
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Full transcript */}
        {timeline?.transcript?.text && (
          <div className="bg-white rounded-2xl border border-surface-100 shadow-sm overflow-hidden">
            <button
              onClick={() => setShowTranscript(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 hover:bg-surface-50 transition-colors cursor-pointer"
            >
              <span className="text-sm font-semibold text-surface-900 flex items-center gap-2">
                <AlignLeft className="w-4 h-4 text-surface-400" />
                Full transcript
                <span className="text-[10px] font-medium text-surface-400 bg-surface-100 px-1.5 py-0.5 rounded-full">
                  {timeline.transcript.language?.toUpperCase()}
                  {timeline.transcript.duration ? ` · ${formatTime(timeline.transcript.duration)}` : ''}
                </span>
              </span>
              {showTranscript ? <ChevronUp className="w-4 h-4 text-surface-400" /> : <ChevronDown className="w-4 h-4 text-surface-400" />}
            </button>
            {showTranscript && (
              <div className="px-4 pb-4 max-h-48 overflow-y-auto custom-scroll">
                <p className="text-xs text-surface-600 leading-relaxed">{timeline.transcript.text}</p>
              </div>
            )}
          </div>
        )}

        {/* Process another */}
        <button
          onClick={() => { setStep('configure'); setTimeline(null); setJob(null); setErrorMsg(null); }}
          className="w-full py-3 rounded-2xl border border-surface-200 bg-white hover:bg-surface-50 text-surface-700 font-semibold text-sm flex items-center justify-center gap-2 transition-colors cursor-pointer"
        >
          <Mic className="w-4 h-4 text-orange-400" />
          Process another video
        </button>
      </div>
    </div>
  );
}
