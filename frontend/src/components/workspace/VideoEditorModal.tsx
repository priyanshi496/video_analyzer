import { useState, useEffect, useRef } from 'react';
import {
  ChevronLeft,
  Play,
  Pause,
  ZoomIn,
  ZoomOut,
  Film,
  Volume2,
  Mic,
  Music,
  Subtitles,
} from 'lucide-react';

interface VideoEditorModalProps {
  url: string;
  onClose: () => void;
  onDownload: () => void;
}

export default function VideoEditorModal({
  url,
  onClose,
  onDownload,
}: VideoEditorModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [trackVolumes, setTrackVolumes] = useState({
    originalSound: 0,
    voice: 78,
    music: 35,
  });
  const [captionsOn, setCaptionsOn] = useState(true);
  const [zoom, setZoom] = useState(100);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const onTime = () => setCurrentTime(v.currentTime);
    const onMeta = () => setDuration(v.duration || 0);
    v.addEventListener('timeupdate', onTime);
    v.addEventListener('loadedmetadata', onMeta);
    return () => {
      v.removeEventListener('timeupdate', onTime);
      v.removeEventListener('loadedmetadata', onMeta);
    };
  }, []);

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play();
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  // Generate fake waveform bars
  const waveformBars = (color: string, count: number, seed: number) =>
    Array.from({ length: count }, (_, i) => {
      const h = 20 + ((Math.sin(i * 0.7 + seed) + 1) / 2) * 80;
      return (
        <div
          key={i}
          className="flex-shrink-0 rounded-sm opacity-90"
          style={{ width: 3, height: `${h}%`, backgroundColor: color }}
        />
      );
    });

  return (
    <div className="fixed inset-0 z-[60] bg-[#111] flex flex-col animate-fade-in">
      {/* ── Top bar ── */}
      <div className="flex items-center justify-between px-4 pt-10 pb-3 bg-[#111]">
        <button onClick={onClose} className="flex items-center gap-2 text-white cursor-pointer">
          <ChevronLeft className="w-5 h-5" />
          <span className="text-sm font-semibold">Back</span>
        </button>
        <span className="text-sm font-bold text-white truncate max-w-[180px]">Edit Reel</span>
        <button
          onClick={onDownload}
          className="px-4 py-1.5 bg-orange-500 hover:bg-orange-600 text-white rounded-full text-xs font-bold transition-all shadow-md cursor-pointer"
        >
          Export
        </button>
      </div>

      {/* ── Video Preview ── */}
      <div className="flex-shrink-0 flex items-center justify-center bg-black" style={{ height: '40vh' }}>
        <div className="h-full aspect-[9/16] relative overflow-hidden">
          <video
            ref={videoRef}
            src={url}
            autoPlay
            playsInline
            loop
            className="h-full w-full object-contain"
          />
        </div>
      </div>

      {/* ── Playback Controls ── */}
      <div className="flex-shrink-0 flex items-center gap-4 px-5 py-3 bg-[#111]">
        <span className="text-[12px] font-mono text-slate-400 w-20">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
        <button
          onClick={togglePlay}
          className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 text-white flex items-center justify-center transition-all cursor-pointer"
        >
          {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
        </button>
        <div className="flex items-center gap-2 ml-auto">
          <button onClick={() => setZoom(z => Math.max(50, z - 25))} className="text-slate-400 hover:text-white transition-colors cursor-pointer">
            <ZoomOut className="w-4 h-4" />
          </button>
          <span className="text-[11px] font-mono text-slate-400 w-12 text-center">{zoom}%</span>
          <button onClick={() => setZoom(z => Math.min(200, z + 25))} className="text-slate-400 hover:text-white transition-colors cursor-pointer">
            <ZoomIn className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── Timeline Progress Scrubber ── */}
      <div className="flex-shrink-0 px-5 pb-1">
        <div className="relative h-1.5 bg-white/10 rounded-full overflow-hidden">
          <div
            className="absolute left-0 top-0 h-full bg-orange-500 rounded-full"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* ── Timestamp ruler ── */}
      <div className="flex-shrink-0 px-5 pt-2 pb-1 overflow-x-auto hide-scrollbar">
        <div className="flex gap-0" style={{ width: `${zoom * 3.5}px`, minWidth: '100%' }}>
          {Array.from({ length: Math.max(4, Math.ceil(duration)) + 1 }, (_, i) => (
            <div key={i} className="flex-1 flex flex-col items-start">
              <div className="w-px h-2 bg-white/20" />
              <span className="text-[9px] font-mono text-slate-500 mt-0.5">{formatTime(i)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Track Rows ── */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden px-0 pb-6" style={{ minHeight: 0 }}>

        {/* Video Track */}
        <div className="flex items-center px-4 py-2 gap-3 border-b border-white/5">
          <div className="flex items-center gap-2 w-28 flex-shrink-0">
            <div className="w-2 h-2 rounded-full bg-orange-400" />
            <span className="text-[11px] font-semibold text-slate-300">Video</span>
          </div>
          <div className="flex-1 overflow-x-auto hide-scrollbar">
            <div
              className="flex gap-0.5 rounded-lg overflow-hidden border border-orange-500/30"
              style={{ width: `${zoom * 3.2}px`, minWidth: 220, height: 44 }}
            >
              {/* Fake video thumbnails */}
              {Array.from({ length: Math.max(3, Math.ceil(zoom / 30)) }, (_, i) => (
                <div key={i} className="flex-1 bg-gradient-to-br from-slate-700 to-slate-600 flex items-center justify-center border-r border-white/5 last:border-r-0">
                  <Film className="w-3 h-3 text-slate-400 opacity-50" />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Original Sound Track */}
        <div className="flex items-center px-4 py-2.5 gap-3 border-b border-white/5">
          <div className="flex items-center gap-2 w-28 flex-shrink-0">
            <Volume2 className="w-3 h-3 text-slate-500" />
            <span className="text-[11px] font-semibold text-slate-500">Original Sound</span>
          </div>
          <div className="flex-1">
            <input
              type="range"
              min={0}
              max={100}
              value={trackVolumes.originalSound}
              onChange={e => setTrackVolumes(v => ({ ...v, originalSound: +e.target.value }))}
              className="w-full accent-slate-400 cursor-pointer h-1"
            />
          </div>
        </div>

        {/* Voice Track */}
        <div className="flex flex-col px-4 py-2 gap-2 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 w-28 flex-shrink-0">
              <Mic className="w-3 h-3 text-emerald-400" />
              <span className="text-[11px] font-semibold text-slate-300">Voice</span>
            </div>
            <div className="flex-1">
              <input
                type="range"
                min={0}
                max={100}
                value={trackVolumes.voice}
                onChange={e => setTrackVolumes(v => ({ ...v, voice: +e.target.value }))}
                className="w-full accent-emerald-400 cursor-pointer h-1"
              />
            </div>
          </div>
          {/* Waveform */}
          <div className="ml-28 flex-1 overflow-x-auto hide-scrollbar">
            <div
              className="flex items-center gap-px"
              style={{ height: 28, width: `${zoom * 3.2}px`, minWidth: 220 }}
            >
              {waveformBars('#34d399', 80, 1.2)}
            </div>
          </div>
        </div>

        {/* Music Track */}
        <div className="flex flex-col px-4 py-2 gap-2 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 w-28 flex-shrink-0">
              <Music className="w-3 h-3 text-blue-400" />
              <span className="text-[11px] font-semibold text-slate-300">Music</span>
            </div>
            <div className="flex-1">
              <input
                type="range"
                min={0}
                max={100}
                value={trackVolumes.music}
                onChange={e => setTrackVolumes(v => ({ ...v, music: +e.target.value }))}
                className="w-full accent-blue-400 cursor-pointer h-1"
              />
            </div>
          </div>
          {/* Waveform */}
          <div className="ml-28 flex-1 overflow-x-auto hide-scrollbar">
            <div
              className="flex items-center gap-px"
              style={{ height: 28, width: `${zoom * 3.2}px`, minWidth: 220 }}
            >
              {waveformBars('#60a5fa', 80, 2.5)}
            </div>
          </div>
        </div>

        {/* Captions Track */}
        <div className="flex items-center px-4 py-3 gap-3">
          <div className="flex items-center gap-2 w-28 flex-shrink-0">
            <Subtitles className="w-3 h-3 text-yellow-400" />
            <span className="text-[11px] font-semibold text-slate-300">Captions</span>
          </div>
          {/* Toggle */}
          <button
            onClick={() => setCaptionsOn(c => !c)}
            className={`w-11 h-6 rounded-full transition-colors cursor-pointer relative flex-shrink-0 ${captionsOn ? 'bg-orange-500' : 'bg-white/10'}`}
          >
            <div className={`absolute top-0.5 w-5 h-5 rounded-full bg-white shadow transition-all ${captionsOn ? 'left-[22px]' : 'left-0.5'}`} />
          </button>
          {captionsOn && (
            <div className="flex-1 overflow-x-auto hide-scrollbar">
              <div
                className="flex gap-1.5 items-center"
                style={{ width: `${zoom * 3.2}px`, minWidth: 220 }}
              >
                {['Seeing the...', 'Mountain...', 'We s...'].map((t, i) => (
                  <div key={i} className="flex-1 min-w-[60px] h-8 rounded-md bg-yellow-500/15 border border-yellow-400/30 flex items-center justify-center px-1.5">
                    <span className="text-[9px] font-semibold text-yellow-300 truncate">{t}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
