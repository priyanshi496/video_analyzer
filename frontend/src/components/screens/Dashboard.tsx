import { useState, useEffect } from 'react';
import { Plus, Film, Folder, Loader2, Calendar, ChevronRight } from 'lucide-react';
import { Button } from '../ui';
import { projectService } from '../../services/projects';
import { formatDate } from '../../lib/utils';
import { useNavigate } from 'react-router-dom';
import type { Project } from '../../types';

export function Dashboard() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

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

  return (
    <div className="flex-1 min-h-screen bg-transparent p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header Section */}
        <div className="mb-8 animate-fade-in">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-surface-900 tracking-tight">
                Your Projects
              </h1>
              <p className="text-surface-500 mt-1">
                Create AI-powered video montages from your clips
              </p>
            </div>
            <Button
              onClick={handleCreateProject}
              loading={creating}
              icon={<Plus className="w-4 h-4" />}
              size="lg"
            >
              New Project
            </Button>
          </div>
        </div>

        {/* Stats Bar */}
        <div className="grid grid-cols-3 gap-4 mb-8 animate-slide-up animation-delay-100">
          <div className="glass rounded-2xl p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-primary-100 flex items-center justify-center">
                <Folder className="w-5 h-5 text-primary-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-surface-900">{projects.length}</p>
                <p className="text-sm text-surface-500">Total Projects</p>
              </div>
            </div>
          </div>
          <div className="glass rounded-2xl p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-success-500/10 flex items-center justify-center">
                <Film className="w-5 h-5 text-success-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-surface-900">
                  {projects.length}
                </p>
                <p className="text-sm text-surface-500">Videos Created</p>
              </div>
            </div>
          </div>
          <div className="glass rounded-2xl p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-accent-100 flex items-center justify-center">
                <Calendar className="w-5 h-5 text-accent-600" />
              </div>
              <div>
                <p className="text-2xl font-bold text-surface-900">This Week</p>
                <p className="text-sm text-surface-500">Active Sessions</p>
              </div>
            </div>
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
              <p className="text-surface-500">Loading projects...</p>
            </div>
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="glass rounded-2xl p-8 text-center">
            <p className="text-error-500">{error}</p>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && projects.length === 0 && (
          <div className="glass rounded-2xl p-16 text-center animate-scale-in">
            <div className="w-20 h-20 rounded-full bg-primary-100 flex items-center justify-center mx-auto mb-4">
              <Film className="w-10 h-10 text-primary-500" />
            </div>
            <h2 className="text-xl font-semibold text-surface-900 mb-2">
              No projects yet
            </h2>
            <p className="text-surface-500 mb-6 max-w-md mx-auto">
              Create your first project and let AI turn your raw footage into
              stunning video montages.
            </p>
            <Button
              onClick={handleCreateProject}
              loading={creating}
              icon={<Plus className="w-4 h-4" />}
              size="lg"
            >
              Create Your First Project
            </Button>
          </div>
        )}

        {/* Project Grid */}
        {!loading && !error && projects.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-slide-up animation-delay-200">
            {/* Create New Card */}
            <button
              onClick={handleCreateProject}
              disabled={creating}
              className="aspect-[4/3] rounded-2xl border-2 border-dashed border-surface-300
                hover:border-primary-400 hover:bg-primary-50/50
                flex flex-col items-center justify-center gap-3
                transition-all duration-300 group animate-scale-in"
            >
              {creating ? (
                <Loader2 className="w-8 h-8 text-surface-400 animate-spin" />
              ) : (
                <>
                  <div className="w-12 h-12 rounded-full bg-surface-100 group-hover:bg-primary-100
                    flex items-center justify-center transition-colors">
                    <Plus className="w-6 h-6 text-surface-400 group-hover:text-primary-500" />
                  </div>
                  <span className="text-surface-500 group-hover:text-primary-600 font-medium">
                    Create New Project
                  </span>
                </>
              )}
            </button>

            {/* Project Cards */}
            {projects.map((project, index) => (
              <ProjectCard
                key={project.id}
                project={project}
                onClick={() => navigate(`/project/${project.id}`)}
                style={{ animationDelay: `${index * 50}ms` }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectCard({
  project,
  onClick,
  style,
}: {
  project: Project;
  onClick: () => void;
  style?: React.CSSProperties;
}) {
  const [thumbnailUrl, setThumbnailUrl] = useState<string | null>(null);
  const [isImage, setIsImage] = useState(false);

  useEffect(() => {
    const fetchMedia = async () => {
      try {
        const media = await projectService.listMedia(project.id);
        if (media && media.length > 0) {
          setThumbnailUrl(media[0].presigned_url);
          setIsImage(media[0].is_image);
        }
      } catch (err) {
        // ignore
      }
    };
    fetchMedia();
  }, [project.id]);

  return (
    <button
      onClick={onClick}
      className="aspect-[4/3] rounded-2xl glass overflow-hidden
        group relative text-left card-hover animate-scale-in"
      style={style}
    >
      {/* Thumbnail placeholder or actual media */}
      <div className="absolute inset-0 bg-gradient-to-br from-primary-400/20 via-accent-400/10 to-surface-100 bg-black">
        {thumbnailUrl && (
          isImage ? (
            <img src={thumbnailUrl} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" />
          ) : (
            <video src={thumbnailUrl + "#t=0.1"} className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-700" preload="metadata" />
          )
        )}
      </div>

      {/* Gradient overlay on hover */}
      <div className="absolute inset-0 bg-gradient-to-t from-surface-900 via-surface-900/50 to-transparent
        opacity-60 group-hover:opacity-80 transition-opacity" />

      {/* Content */}
      <div className="absolute inset-x-0 bottom-0 p-5 z-10">
        <h3 className="text-lg font-semibold text-white mb-1 truncate group-hover:text-primary-200 transition-colors">
          {project.name}
        </h3>
        <div className="flex items-center justify-between">
          <span className="text-sm text-surface-300">
            {formatDate(project.created_at)}
          </span>
          <div className="w-8 h-8 rounded-full bg-white/10 backdrop-blur flex items-center justify-center
            group-hover:bg-primary-500 transition-all group-hover:translate-x-1">
            <ChevronRight className="w-4 h-4 text-white" />
          </div>
        </div>
      </div>

      {/* Folder icon */}
      <div className="absolute top-4 left-4">
        <div className="w-10 h-10 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center">
          <Folder className="w-5 h-5 text-white" />
        </div>
      </div>
    </button>
  );
}
