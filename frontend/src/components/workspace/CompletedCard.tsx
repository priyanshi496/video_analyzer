import { useState } from 'react';
import { Maximize2, Download, RotateCcw } from 'lucide-react';
import { triggerDownload } from '../../lib/utils';

interface CompletedCardProps {
  url: string;
  onReset: () => void;
  onPreview: () => void;
}

export default function CompletedCard({
  url,
  onReset,
  onPreview,
}: CompletedCardProps) {
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    setDownloading(true);
    await triggerDownload(url);
    setDownloading(false);
  };

  return (
    <div className="animate-slide-up space-y-4 max-w-[92%] sm:max-w-[340px] flex flex-col items-center w-full mx-auto sm:mx-0">
      <div className="bg-white rounded-3xl shadow-lg border border-orange-100/60 overflow-hidden w-full">
        {/* Video Container - Portrait (9:16) */}
        <div className="aspect-[9/16] bg-slate-950 relative group">
          <video src={url} controls playsInline className="w-full h-full object-contain" />
          
          {/* Custom Fullscreen Trigger Button overlay */}
          <button
            onClick={onPreview}
            className="absolute top-3 right-3 z-10 w-9 h-9 rounded-full bg-black/60 hover:bg-black/80 text-white flex items-center justify-center transition-all opacity-0 group-hover:opacity-100 cursor-pointer"
            title="Open Preview Popup"
          >
            <Maximize2 className="w-4 h-4 text-white" />
          </button>
        </div>
        
        <div className="p-4.5 flex items-center justify-between gap-4">
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-900 truncate">Your reel is ready!</p>
            <p className="text-[11px] font-semibold text-slate-400 mt-0.5">Tap to watch or download</p>
          </div>
          <button
            onClick={handleDownload}
            disabled={downloading}
            className="flex items-center gap-1.5 px-4.5 py-2 bg-orange-500 hover:bg-orange-600 disabled:bg-orange-400 text-white rounded-full text-xs font-bold shadow-md shadow-orange-500/10 active:scale-95 transition-all cursor-pointer flex-shrink-0"
          >
            {downloading ? (
              <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            Save
          </button>
        </div>
      </div>

      <button
        onClick={onReset}
        className="flex items-center gap-2 px-5 py-2.5 rounded-full bg-white shadow-sm border border-slate-200 text-xs font-bold text-slate-600 hover:border-orange-400 hover:text-orange-500 transition-all cursor-pointer"
      >
        <RotateCcw className="w-3.5 h-3.5" />
        Make another version
      </button>
    </div>
  );
}
