import { useState, useEffect } from 'react';
import { Play, Loader2, FolderOpen } from 'lucide-react';
import { projectService } from '../services/projects';
import type { Project, MediaAsset } from '../types';

export default function GridScreen() {
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'video' | 'image'>('all');

  useEffect(() => {
    const fetchAllMedia = async () => {
      try {
        const projectsData: Project[] = await projectService.getProjects();
        let allMedia: MediaAsset[] = [];
        for (const p of projectsData) {
          const projectMedia = await projectService.listMedia(p.id);
          allMedia = allMedia.concat(projectMedia);
        }
        setMedia(allMedia);
      } catch (err) {
        console.error('Failed to load media grid:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchAllMedia();
  }, []);

  const filteredMedia = media.filter(m => {
    if (filter === 'video') return !m.is_image;
    if (filter === 'image') return m.is_image;
    return true;
  });

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center bg-slate-50 p-8">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
        <span className="text-sm text-slate-500 mt-2">Loading library...</span>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-slate-50 p-4 overflow-y-auto pb-20 sm:pb-8 text-left">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-slate-800">Media Library</h2>
        <span className="text-xs text-slate-500 font-semibold bg-slate-100 py-1 px-3 rounded-full">
          {media.length} items
        </span>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2 mb-4">
        {['all', 'video', 'image'].map(type => (
          <button 
            key={type}
            onClick={() => setFilter(type as any)}
            className={`px-4 py-1.5 rounded-full text-xs font-semibold border transition-all ${filter === type ? 'bg-orange-600 text-white border-orange-600' : 'bg-white text-slate-600 border-slate-200'}`}
          >
            <span className="capitalize">{type}s</span>
          </button>
        ))}
      </div>

      {filteredMedia.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-3xl border border-slate-100 shadow-sm">
          <FolderOpen className="w-8 h-8 text-slate-300 mx-auto mb-2" />
          <p className="text-sm text-slate-500">No media assets found matching filter.</p>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2">
          {filteredMedia.map(item => (
            <div key={item.id} className="aspect-square rounded-2xl overflow-hidden relative border border-slate-100 bg-slate-200">
              {item.presigned_url && (
                item.is_image ? (
                  <img src={item.presigned_url} className="w-full h-full object-cover" loading="lazy" />
                ) : (
                  <video src={item.presigned_url + '#t=0.1'} className="w-full h-full object-cover" preload="metadata" />
                )
              )}
              {!item.is_image && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/10">
                  <Play className="w-4 h-4 text-white fill-white opacity-80" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
