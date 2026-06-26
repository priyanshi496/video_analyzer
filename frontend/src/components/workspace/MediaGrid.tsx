import { Plus, Trash2 } from 'lucide-react';
import type { MediaAsset } from '../../types';

interface MediaGridProps {
  assets: MediaAsset[];
  onDelete: (id: string) => void;
  onAddMore: () => void;
  locked: boolean;
  uploading: boolean;
}

export default function MediaGrid({
  assets,
  onDelete,
  onAddMore,
  locked,
  uploading,
}: MediaGridProps) {
  return (
    <div className="pt-2 flex justify-end animate-fade-in w-full">
      <div className="w-full max-w-[70%]">
        <div className="flex flex-wrap justify-end gap-1.5">
          {assets.map(asset => (
            <div key={asset.id} className="relative group w-20 h-20 rounded-xl overflow-hidden bg-surface-200">
              {/* Thumbnail */}
              {asset.is_image ? (
                <img
                  src={asset.thumbnail_url || asset.presigned_url || ''}
                  alt={asset.filename}
                  className="w-full h-full object-cover"
                />
              ) : (
                <video
                  src={(asset.thumbnail_url || asset.presigned_url || '') + '#t=0.1'}
                  className="w-full h-full object-cover"
                />
              )}

              {/* Delete overlay */}
              {!locked && (
                <button
                  onClick={() => onDelete(asset.id)}
                  className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity z-10"
                >
                  <Trash2 className="w-2.5 h-2.5 text-white" />
                </button>
              )}
            </div>
          ))}

          {/* Add more tile */}
          {!locked && (
            <button
              onClick={onAddMore}
              disabled={uploading}
              className="w-20 h-20 rounded-xl border-2 border-dashed border-surface-300 flex items-center justify-center hover:border-orange-400 hover:bg-white/50 transition-all duration-200 bg-white/30"
            >
              {uploading
                ? <div className="w-4 h-4 border border-surface-300 border-t-orange-500 rounded-full animate-spin" />
                : <Plus className="w-5 h-5 text-surface-400" />
              }
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
