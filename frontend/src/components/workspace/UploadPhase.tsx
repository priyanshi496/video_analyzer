import { useState } from 'react';
import { Film, Plus, Download } from 'lucide-react';
import { triggerDownload } from '../../lib/utils';

interface UploadPhaseProps {
  onPickFiles: () => void;
  uploading: boolean;
  pastJobs?: any[];
  onPreviewReel: (url: string) => void;
}

export default function UploadPhase({
  onPickFiles,
  uploading,
  pastJobs = [],
  onPreviewReel,
}: UploadPhaseProps) {
  const [dragActive, setDragActive] = useState(false);

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-8 gap-8 overflow-y-auto pb-10 pt-10 custom-scroll">
      <div className="text-center">
        <h2 className="text-2xl font-semibold text-surface-900 tracking-tight">Start your reel</h2>
        <p className="text-surface-500 mt-1.5 text-sm leading-relaxed">
          Upload your video clips and photos. AI will do the rest.
        </p>
      </div>

      <button
        onClick={onPickFiles}
        onDragOver={e => { e.preventDefault(); setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={e => {
          e.preventDefault();
          setDragActive(false);
        }}
        disabled={uploading}
        className={`
          w-full max-w-sm aspect-[4/3] flex-shrink-0 rounded-3xl border-2 border-dashed
          flex flex-col items-center justify-center gap-4
          transition-all duration-300
          ${dragActive
            ? 'border-orange-500 bg-orange-50'
            : 'border-surface-300 bg-white/60 hover:border-orange-400 hover:bg-white/90'}
        `}
      >
        {uploading ? (
          <div className="flex flex-col items-center gap-3">
            <div className="w-10 h-10 border-2 border-surface-200 border-t-orange-500 rounded-full animate-spin" />
            <span className="text-sm text-surface-500">Uploading...</span>
          </div>
        ) : (
          <>
            <div className={`
              w-16 h-16 rounded-2xl flex items-center justify-center
              ${dragActive ? 'bg-orange-500' : 'bg-surface-100'}
              transition-colors
            `}>
              <Plus className={`w-8 h-8 ${dragActive ? 'text-white' : 'text-surface-400'}`} />
            </div>
            <div className="text-center">
              <p className="font-medium text-surface-800">Drop files here</p>
              <p className="text-sm text-surface-400 mt-1">MP4 · MOV · JPG · PNG</p>
            </div>
          </>
        )}
      </button>

      <p className="text-xs text-surface-400 text-center">
        You can upload multiple clips and photos at once
      </p>

      {/* Past Reels */}
      {pastJobs.length > 0 && (
        <div className="w-full max-w-sm mt-8 animate-fade-in border-t border-surface-200 pt-8 pb-4">
          <h3 className="text-lg font-semibold text-surface-900 mb-4 flex items-center gap-2">
            <Film className="w-5 h-5 text-orange-500" />
            Past Reels
          </h3>
          <div className="space-y-4">
            {pastJobs.map((pastJob) => (
              <div key={pastJob.id} className="bg-white rounded-xl p-4 flex gap-4 items-center border border-surface-200 hover:border-orange-200 transition-colors shadow-sm">
                {/* Thumbnail */}
                <div className="w-24 h-16 bg-black rounded-lg overflow-hidden relative flex-shrink-0">
                  {pastJob.final_video_url ? (
                    <button
                      onClick={() => onPreviewReel(pastJob.final_video_url)}
                      className="absolute inset-0 block group/video w-full h-full text-left cursor-pointer"
                    >
                      <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                      <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                        <Film className="w-6 h-6 text-white opacity-100 transition-opacity" />
                      </div>
                    </button>
                  ) : (
                    <div className="absolute inset-0 flex items-center justify-center bg-surface-100">
                      <Film className="w-6 h-6 text-surface-300" />
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm font-medium text-surface-900 capitalize mb-1">
                    {pastJob.vibe} Reel
                  </p>
                  <p className="text-xs text-slate-500 truncate">
                    {new Date(pastJob.created_at).toLocaleDateString()}
                  </p>
                </div>

                {/* Actions */}
                {pastJob.final_video_url && (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => triggerDownload(pastJob.final_video_url)}
                      title="Download Reel"
                      className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors cursor-pointer"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
