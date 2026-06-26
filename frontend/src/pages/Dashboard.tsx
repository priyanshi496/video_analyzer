import { useState, useEffect } from 'react';
import { Plus, Film, Folder, Loader2, Trash2, SlidersHorizontal } from 'lucide-react';
import { Button } from '../components/ui';
import { projectService } from '../services/projects';
import { useNavigate } from 'react-router-dom';
import type { Project } from '../types';

function relativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(mins / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);
  if (weeks > 0) return `${weeks}w`;
  if (days > 0) return `${days}d`;
  if (hours > 0) return `${hours}h`;
  return `${mins}m`;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<string | null>(null);

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const data = await projectService.getProjects();
        setProjects(data);
      } catch (err) {
        setError('Failed to load projects');
      } finally {
        setLoading(false);
      }
    };
    fetchProjects();
  }, []);

  const handleCreateProject = async () => {
    setCreating(true);
    try {
      const name = `Project ${projects.length + 1}`;
      const project = await projectService.createProject(name);
      navigate(`/project/${project.id}`);
    } catch (err) {
      console.error(err);
      alert('Failed to create project');
    } finally {
      setCreating(false);
    }
  };

  const confirmDeleteProject = async () => {
    if (!projectToDelete) return;
    try {
      await projectService.deleteProject(projectToDelete);
      setProjects(prev => prev.filter(p => p.id !== projectToDelete));
    } catch (err) {
      console.error(err);
      alert('Failed to delete project');
    } finally {
      setProjectToDelete(null);
    }
  };

  return (
    <div className="flex-1 min-h-screen bg-orange-50/30 pb-20 sm:pb-8">

      {/* ── Mobile header ── */}
      <div className="sm:hidden flex items-center justify-between px-4 pt-6 pb-3">
        <h1 className="font-display text-[22px] font-bold text-slate-900 tracking-tight">
          Projects <span className="text-orange-300 font-normal text-lg">›</span>
        </h1>
        <div className="flex items-center gap-3">
          <span className="font-display text-[11px] font-semibold text-orange-600 bg-orange-100 px-2.5 py-1 rounded-full">
            {projects.length} total
          </span>
          <button className="w-9 h-9 flex items-center justify-center rounded-full bg-white border border-orange-100 shadow-sm">
            <SlidersHorizontal className="w-4 h-4 text-orange-500" />
          </button>
          <div className="w-9 h-9 rounded-full bg-gradient-to-br from-orange-400 to-orange-500 flex items-center justify-center shadow-sm">
            <span className="text-white text-xs font-bold">P</span>
          </div>
        </div>
      </div>

      {/* ── Desktop header ── */}
      <div className="hidden sm:block px-8 pt-10 mb-10 animate-fade-in">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-4">
            <h1 className="font-display text-[36px] font-extrabold text-slate-900 tracking-tight leading-none">Your Projects</h1>
            <span className="font-display px-3 py-0.5 bg-orange-500/10 text-orange-600 text-[12px] font-bold rounded-full border border-orange-500/20 backdrop-blur-sm animate-scale-in tracking-wide">
              {projects.length} active
            </span>
          </div>
          <p className="font-sans text-[15px] text-slate-500 mt-3 leading-relaxed">Create AI-powered video montages from your clips</p>
        </div>
      </div>


      {/* ── Main content ── */}
      <div className="px-3 sm:px-8 max-w-6xl sm:mx-auto">

        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
              <p className="text-sm font-medium text-slate-400">Loading projects...</p>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-white/80 backdrop-blur-sm rounded-2xl p-8 text-center border border-red-100 shadow-sm">
            <p className="text-sm font-medium text-red-500">{error}</p>
          </div>
        )}

        {!loading && !error && projects.length === 0 && (
          <div className="bg-white/80 backdrop-blur-sm rounded-2xl p-16 text-center border border-orange-100 shadow-sm animate-scale-in">
            <div className="w-20 h-20 rounded-full bg-orange-50 flex items-center justify-center mx-auto mb-4">
              <Film className="w-10 h-10 text-orange-400" />
            </div>
            <h2 className="text-xl font-bold text-slate-900 mb-2">No projects yet</h2>
            <p className="text-sm font-medium text-slate-400 mb-8 max-w-md mx-auto leading-relaxed">
              Create your first project and let AI turn your raw footage into stunning video montages.
            </p>
            <Button onClick={handleCreateProject} loading={creating} icon={<Plus className="w-4 h-4" />} size="lg">
              Create Your First Project
            </Button>
          </div>
        )}

        {!loading && !error && projects.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3 sm:gap-5 animate-slide-up animation-delay-200">

            {/* Desktop-only: dashed "New Project" card */}
            <button
              onClick={handleCreateProject}
              disabled={creating}
              className="hidden sm:flex aspect-[3/4] rounded-2xl border-2 border-dashed border-orange-200/80
                hover:border-orange-400 hover:bg-orange-50/30
                flex-col items-center justify-center gap-2
                transition-all duration-300 group cursor-pointer"
            >
              {creating ? (
                <Loader2 className="w-5 h-5 text-orange-400 animate-spin" />
              ) : (
                <>
                  <div className="w-10 h-10 rounded-full bg-orange-50 group-hover:bg-orange-100/80 flex items-center justify-center transition-colors">
                    <Plus className="w-5 h-5 text-orange-500 group-hover:text-orange-600" />
                  </div>
                  <span className="font-display text-[13px] font-semibold text-orange-500 group-hover:text-orange-600 tracking-wide mt-1">
                    New Project
                  </span>
                </>
              )}
            </button>

            {/* Project cards */}
            {projects.map((project, index) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => navigate(`/project/${project.id}`)}
                onDelete={() => setProjectToDelete(project.id)}
                style={{ animationDelay: `${index * 50}ms` }}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── Mobile FAB ── */}
      <button
        onClick={handleCreateProject}
        disabled={creating}
        className="sm:hidden fixed bottom-20 right-4 w-12 h-12 rounded-full bg-orange-500 text-white shadow-lg shadow-orange-500/25 flex items-center justify-center z-50 active:scale-95 transition-transform"
        aria-label="New project"
      >
        {creating ? <Loader2 className="w-5 h-5 animate-spin" /> : <Plus className="w-5 h-5" />}
      </button>

      {/* ── Custom Delete Confirmation Modal ── */}
      {projectToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 modal-overlay animate-fade-in">
          <div className="bg-white/95 backdrop-blur-md rounded-2xl border border-orange-100/50 shadow-2xl max-w-sm w-full p-6 animate-scale-in flex flex-col gap-4">
            <div className="flex items-center gap-3 text-red-500">
              <div className="w-10 h-10 rounded-xl bg-red-50 flex items-center justify-center">
                <Trash2 className="w-5 h-5 text-red-500" />
              </div>
              <h3 className="font-display text-lg font-bold text-slate-900">Delete Project</h3>
            </div>
            
            <p className="font-sans text-xs font-medium text-slate-500 leading-relaxed">
              Are you sure you wanna delete this project? This will permanently remove all associated media files and generated reels.
            </p>
            
            <div className="flex items-center justify-end gap-3 mt-2">
              <button
                onClick={() => setProjectToDelete(null)}
                className="px-4 py-2 text-xs font-semibold text-slate-500 hover:text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200/80 rounded-xl transition-all duration-200 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteProject}
                className="px-4 py-2 text-xs font-semibold text-white bg-red-500 hover:bg-red-600 rounded-xl shadow-lg shadow-red-500/20 active:scale-95 transition-all duration-200 cursor-pointer"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  onClick,
  onDelete,
  style,
}: {
  project: Project;
  onClick: () => void;
  onDelete: () => void;
  style?: React.CSSProperties;
}) {
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [isImage, setIsImage] = useState(false);
  const [mediaSize, setMediaSize] = useState<number | null>(null);

  useEffect(() => {
    const fetchMedia = async () => {
      try {
        const media = await projectService.listMedia(project.id);
        if (media && media.length > 0) {
          setThumbnailUrl(media[0].presigned_url);
          setIsImage(media[0].is_image);
          setMediaSize(media[0].size_bytes ?? null);
        }
      } catch (err) {
        // ignore
      }
    };
    fetchMedia();
  }, [project.id]);

  const sizeLabel = mediaSize
    ? mediaSize > 1_000_000
      ? `${(mediaSize / 1_000_000).toFixed(0)} MB`
      : `${(mediaSize / 1_000).toFixed(0)} KB`
    : null;

  return (
    <div className="flex flex-col" style={style}>
      <div
        onClick={onClick}
        className="aspect-[3/4] overflow-hidden cursor-pointer relative rounded-xl sm:rounded-2xl bg-white border border-slate-100 shadow-sm hover:shadow-md group card-hover animate-scale-in"
      >
        <div className="absolute inset-0 bg-orange-50/60">
          {thumbnailUrl ? (
            isImage ? (
              <img src={thumbnailUrl} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" loading="lazy" />
            ) : (
              <video src={thumbnailUrl + '#t=0.1'} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" preload="metadata" />
            )
          ) : (
            <div className="w-full h-full flex items-center justify-center bg-orange-50/30">
              <Folder className="w-6 h-6 text-orange-300" />
            </div>
          )}
        </div>

        {/* Hover overlay with project name and date */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/45 to-transparent flex flex-col justify-end p-3.5 sm:p-5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-all duration-300 z-10 pointer-events-none">
          <h3 className="font-display text-sm sm:text-base font-bold text-white group-hover:text-orange-400 group-hover:scale-[1.08] transition-all duration-300 origin-bottom-left truncate leading-tight mb-1">
            {project.name}
          </h3>
          <span className="font-sans text-[11px] sm:text-[12px] font-medium text-white/80">
            {relativeTime(project.created_at)}
            {sizeLabel && <> · {sizeLabel}</>}
          </span>
        </div>

        {/* Delete — desktop hover only */}
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          className="absolute top-2 right-2 z-20 w-8 h-8 rounded-lg bg-white/90 hover:bg-red-500 hover:text-white border border-red-100 text-red-500 backdrop-blur-sm items-center justify-center transition-all duration-300 opacity-0 group-hover:opacity-100 hidden sm:flex cursor-pointer"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
