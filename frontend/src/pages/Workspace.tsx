import { useState, useCallback, useRef, useEffect } from 'react';
import {
  ArrowLeft,
  Download,
  Film,
  X,
  Scissors,
  Mic,
  Music,
  Pencil,
  Check,
  MoreHorizontal,
  MessageSquare,
  Volume2,
  RefreshCw,
  Play,
  Pause,
} from 'lucide-react';
import { useParams, useNavigate } from 'react-router-dom';
import { useWorkspace } from '../hooks/useWorkspace';
import { vibeOptions, musicModeOptions, triggerDownload } from '../lib/utils';
import type { GenerationConfig } from '../types';

// Import subcomponents
import UploadPhase from '../components/workspace/UploadPhase';
import MediaGrid from '../components/workspace/MediaGrid';
import ChatQuestion from '../components/workspace/ChatQuestion';
import ProcessingBubble from '../components/workspace/ProcessingBubble';
import StoryCard from '../components/workspace/StoryCard';
import CompletedCard from '../components/workspace/CompletedCard';
import FailedCard from '../components/workspace/FailedCard';
import ChatInputBar from '../components/workspace/ChatInputBar';
import VideoEditorModal from '../components/workspace/VideoEditorModal';
import { TemplatePicker } from '../components/workspace/TemplatePicker';
import { TemplateEditor } from '../components/workspace/TemplateEditor';
import { templatesService } from '../services/templates';
import type { VideoTemplate } from '../services/templates';

// Chat flow phases
type ChatPhase =
  | 'upload'       // no media yet
  | 'vibe'         // asking vibe preference
  | 'music'        // asking music mode
  | 'song_query'   // custom song text input
  | 'processing'   // PENDING / RUNNING
  | 'story'        // STORY_PROPOSED
  | 'rendering'    // confirmed story, rendering
  | 'complete'     // COMPLETED
  | 'failed';      // FAILED

interface ConfigState {
  vibe: GenerationConfig['vibe'];
  musicMode: GenerationConfig['musicMode'];
  instrumentalOnly: boolean;
  directives: string;
  songQuery: string;
}

const analysisMessages = [
  'Looking at your pics...',
  'Wow, so beautiful!',
  'Analyzing quality...',
  'Oh, this one is a lil shaky...',
  'Finding the perfect highlights...',
  'Scanning for the best frames...',
  'This is going to look amazing...',
  'Going through your clips...',
  'Taking it all in...',
  'Okay, what do we have here...',
  'Checking the quality...',
  'Is this one sharp enough...',
  'A little blurry, but salvageable...',
  'This one is steady, nice...',
  'Hmm, bit shaky on this clip...',
  'Stabilizing in my head...',
  'Rating each shot...',
  'Sorting the good from the meh...',
  'Hmm, interesting...',
  'Flipping through everything...',
  'Reading the room...',
  'Getting the full picture...',
  'Noting the details...',
  'Flagging the wobbly ones...',
  'Checking for motion blur...',
  'Some of these are really sharp...',
  'Filtering out the rough ones...',
  'Keeping only the good stuff...',
  'Quality check, almost done...',
  'Getting a feel for the vibe...',
  'Understanding the story...',
  'Almost have a sense of it...',
  'Just need a moment more...',
];

const renderMessages = [
  'Analyzing your best moments.',
  'Finding the perfect sequence.',
  'Generating script.',
  'Cooking up your next viral cut.',
  'Syncing vibe, voice, and visuals.',
  'Stitching the story together.',
  'Matching beats to your clips.',
  'Laying down the timeline...',
  'Cutting to the good parts...',
  'Sequencing the shots...',
  'Locking in the transitions...',
  'Rendering frame by frame...',
  'Building the final cut...',
  'Mixing the audio...',
  'Syncing the music drop...',
  'Polishing every second...',
  'Adding the finishing layers...',
  'Encoding the magic...',
  'Almost out of the oven...',
  'Final render in progress...',
  'Exporting your masterpiece...',
  'Putting the bow on it...',
  'This one slaps, trust.',
  'Done is near.',
];

export default function Workspace() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const onBack = () => navigate('/');

  const {
    project,
    mediaAssets,
    job,
    setJob,
    jobHistory,
    loading,
    uploading,
    workspaceError,
    uploadFile,
    deleteAsset,
    startGeneration,
    confirmStory,
    regenerateStory,
    resetJob,
    renameProject,
  } = useWorkspace(projectId || '');

  const pastJobs = jobHistory?.filter((h: any) => h.id !== job?.id && h.status === 'COMPLETED') || [];

  const [chatPhase, setChatPhase] = useState<ChatPhase>('upload');
  const [showPastReels, setShowPastReels] = useState(false);
  const [isEditingName, setIsEditingName] = useState(false);
  const [tempName, setTempName] = useState('');
  const [config, setConfig] = useState<ConfigState>({
    vibe: 'cinematic',
    musicMode: 'ai-catalog',
    instrumentalOnly: false,
    directives: '',
    songQuery: '',
  });
  const [rewriteInstruction, setRewriteInstruction] = useState('');
  const [editingStory, setEditingStory] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [inputText, setInputText] = useState('');
  const [activePreviewUrl, setActivePreviewUrl] = useState<string | null>(null);
  const [showEditorUrl, setShowEditorUrl] = useState<string | null>(null);
  const [isFullscreenPlaying, setIsFullscreenPlaying] = useState(true);
  const fullscreenVideoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (activePreviewUrl) {
      setIsFullscreenPlaying(true);
    }
  }, [activePreviewUrl]);

  const toggleFullscreenPlay = () => {
    if (!fullscreenVideoRef.current) return;
    if (isFullscreenPlaying) {
      fullscreenVideoRef.current.pause();
      setIsFullscreenPlaying(false);
    } else {
      fullscreenVideoRef.current.play().catch(() => {});
      setIsFullscreenPlaying(true);
    }
  };

  // Templates Mode States
  const [activeMode, setActiveMode] = useState<'ai' | 'templates'>('ai');
  const [selectedTemplate, setSelectedTemplate] = useState<VideoTemplate | null>(null);

  const handleTemplateRender = async (slotsMapping: any) => {
    try {
      setChatPhase('processing'); // Go to processing state to show progress
      setActiveMode('ai'); // Go back to AI tab to view rendering progress bubble
      const res = await templatesService.renderFromTemplate(projectId || '', selectedTemplate!.id, slotsMapping);
      setJob(res);
      setSelectedTemplate(null);
    } catch (e: any) {
      console.error(e);
      alert(`Template render failed: ${e.message || e}`);
      setChatPhase('failed');
    }
  };

  const handleStartRename = () => {
    setTempName(project?.name || '');
    setIsEditingName(true);
  };

  const handleSaveRename = async () => {
    const trimmed = tempName.trim();
    if (trimmed && trimmed !== project?.name) {
      try {
        await renameProject(trimmed);
      } catch (e) {
        // ignore/revert
      }
    }
    setIsEditingName(false);
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const storyTextareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatPhase, job?.status]);

  // Lock body scroll when any modal is open
  useEffect(() => {
    const isModalOpen = showPastReels || !!activePreviewUrl || !!showEditorUrl;
    if (isModalOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [showPastReels, activePreviewUrl, showEditorUrl]);

  // Advance phase after first upload
  useEffect(() => {
    if (mediaAssets.length > 0 && chatPhase === 'upload') {
      setChatPhase('vibe');
    }
  }, [mediaAssets.length, chatPhase]);

  // Sync job status to chat phase
  useEffect(() => {
    if (!job) return;

    if (job.status === 'PENDING' || job.status === 'RUNNING') {
      if (job.story_summary) {
        setChatPhase('rendering');
      } else {
        setChatPhase('processing');
      }
    } else if (job.status === 'STORY_PROPOSED') {
      setChatPhase('story');
    } else if (job.status === 'COMPLETED') {
      setChatPhase('complete');
    } else if (job.status === 'FAILED') {
      setChatPhase('failed');
    }
  }, [job?.status, job?.story_summary]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    for (const file of files) {
      if (file.type.startsWith('video/') || file.type.startsWith('image/')) {
        await uploadFile(file);
      }
    }
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [uploadFile]);

  const handleVibeSelect = (vibe: ConfigState['vibe']) => {
    setConfig(prev => ({ ...prev, vibe }));
    setTimeout(() => setChatPhase('music'), 400);
  };

  const handleMusicSelect = (musicMode: ConfigState['musicMode']) => {
    setConfig(prev => {
      const updated = { ...prev, musicMode };
      if (musicMode !== 'custom') {
        // Start generation directly!
        startGeneration(updated);
        setTimeout(() => setChatPhase('processing'), 400);
      } else {
        // Go to custom song query text input phase
        setTimeout(() => setChatPhase('song_query'), 400);
      }
      return updated;
    });
  };

  const handleSendSongQuery = () => {
    const query = inputText.trim();
    if (!query) return;
    setInputText('');
    
    setConfig(prev => {
      const updated = { ...prev, songQuery: query };
      startGeneration(updated);
      return updated;
    });
    setChatPhase('processing');
  };

  const handleConfirmStory = async () => {
    setConfirming(true);
    setChatPhase('rendering');
    try {
      if (editingStory && rewriteInstruction.trim()) {
        // User typed instructions in the box
        await confirmStory(job?.story_summary || '', rewriteInstruction.trim());
      } else {
        // User did not edit the box
        await confirmStory(job?.story_summary || '', '');
      }
    } catch (err) {
      // Revert back if it failed so user isn't stuck
      setChatPhase('story');
    } finally {
      setConfirming(false);
    }
  };

  const handleRegenerateStory = async () => {
    setIsRegenerating(true);
    try {
      await regenerateStory();
    } catch (err) {
      console.error(err);
    } finally {
      setIsRegenerating(false);
    }
  };

  const handleResetAll = () => {
    resetJob();
    setChatPhase(mediaAssets.length > 0 ? 'vibe' : 'upload');
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#F2F1EC]">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-surface-300 border-t-orange-500 rounded-full animate-spin" />
          <p className="text-surface-500 text-sm">Loading project...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-[#F2F1EC] relative overflow-hidden min-h-0">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept="video/*,image/*"
        className="hidden"
        onChange={handleFileSelect}
      />

      {/* Error Toast */}
      {workspaceError && (
        <div className="absolute top-16 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2.5 bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-2.5 shadow-md animate-slide-up">
          <span className="flex-1">{workspaceError}</span>
        </div>
      )}

      {/* Top bar */}
      <div className="flex items-center justify-between px-5 py-3.5 bg-transparent">
        <button
          onClick={onBack}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-surface-700" />
        </button>
        {isEditingName ? (
          <div className="flex-1 max-w-[220px] mx-2 flex items-center gap-1.5 bg-white border border-orange-300 rounded-full px-3 py-1 shadow-sm animate-scale-in">
            <input
              type="text"
              value={tempName}
              onChange={(e) => setTempName(e.target.value)}
              onBlur={handleSaveRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveRename();
                if (e.key === 'Escape') setIsEditingName(false);
              }}
              autoFocus
              className="w-full bg-transparent text-sm font-semibold text-slate-850 focus:outline-none text-center"
              maxLength={50}
            />
            <button
              onClick={handleSaveRename}
              className="p-0.5 text-orange-500 hover:text-orange-600 hover:bg-orange-50 rounded-full transition-colors cursor-pointer"
            >
              <Check className="w-3.5 h-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={handleStartRename}
            className="flex items-center gap-1.5 text-sm font-semibold text-surface-700 hover:text-orange-500 hover:bg-white/65 hover:shadow-sm px-3.5 py-1.5 rounded-full transition-all max-w-[220px] min-w-0 truncate group cursor-pointer"
            title="Rename Project"
          >
            <span className="truncate">{project?.name || 'Project'}</span>
            <Pencil className="w-3 h-3 text-surface-450 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0" />
          </button>
        )}
        <button
          onClick={() => setShowPastReels(true)}
          className="w-9 h-9 rounded-full bg-surface-200/80 flex items-center justify-center hover:bg-surface-300/80 transition-colors"
        >
          <MoreHorizontal className="w-4 h-4 text-surface-700" />
        </button>
      </div>

      {/* Past Reels Modal */}
      {showPastReels && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm max-h-[80vh] flex flex-col overflow-hidden animate-slide-up">
            <div className="px-5 py-4 border-b border-surface-200 flex items-center justify-between bg-surface-50">
              <h3 className="text-lg font-semibold text-surface-900 flex items-center gap-2">
                <Film className="w-5 h-5 text-orange-500" />
                Past Reels
              </h3>
              <button onClick={() => setShowPastReels(false)} className="p-2 text-surface-400 hover:text-surface-700 hover:bg-surface-200 rounded-full transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-5 overflow-y-auto custom-scroll space-y-4">
              {pastJobs.length > 0 ? pastJobs.map((pastJob) => (
                <div key={pastJob.id} className="bg-white rounded-xl p-3 flex gap-3 items-center border border-surface-200 hover:border-orange-200 transition-colors shadow-sm">
                  <div className="w-20 h-14 bg-black rounded-lg overflow-hidden relative flex-shrink-0">
                    {pastJob.final_video_url ? (
                      <button
                        onClick={() => setActivePreviewUrl(pastJob.final_video_url)}
                        className="absolute inset-0 block group/video w-full h-full text-left cursor-pointer"
                      >
                        <video src={pastJob.final_video_url + "#t=0.1"} preload="metadata" className="w-full h-full object-cover group-hover/video:scale-105 transition-transform duration-300" />
                        <div className="absolute inset-0 bg-black/20 group-hover/video:bg-black/10 transition-colors flex items-center justify-center">
                          <Film className="w-4 h-4 text-white opacity-100 transition-opacity" />
                        </div>
                      </button>
                    ) : (
                      <div className="absolute inset-0 flex items-center justify-center bg-surface-100">
                        <Film className="w-5 h-5 text-surface-300" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0 text-left">
                    <p className="text-sm font-medium text-surface-900 capitalize mb-0.5 truncate">{pastJob.vibe} Reel</p>
                    <p className="text-xs text-slate-500 truncate">{new Date(pastJob.created_at).toLocaleDateString()}</p>
                  </div>
                  {pastJob.final_video_url && (
                    <button
                      onClick={() => triggerDownload(pastJob.final_video_url)}
                      title="Download Reel"
                      className="p-2 rounded-lg bg-surface-100 text-surface-600 hover:bg-orange-50 hover:text-orange-600 transition-colors cursor-pointer"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )) : (
                <div className="text-center py-8">
                  <Film className="w-8 h-8 text-surface-300 mx-auto mb-3" />
                  <p className="text-surface-500 text-sm">No past reels found.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Mode Switcher */}
      {chatPhase !== 'upload' && !['processing', 'rendering'].includes(chatPhase) && (
        <div className="flex justify-center my-3 flex-shrink-0">
          <div className="bg-zinc-200/80 p-1 rounded-full flex gap-1 shadow-inner border border-white/10">
            <button
              onClick={() => setActiveMode('ai')}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                activeMode === 'ai'
                  ? 'bg-orange-500 text-white shadow-sm'
                  : 'text-zinc-600 hover:text-zinc-950'
              }`}
            >
              🤖 Smart AI
            </button>
            <button
              onClick={() => setActiveMode('templates')}
              className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                activeMode === 'templates'
                  ? 'bg-orange-500 text-white shadow-sm'
                  : 'text-zinc-600 hover:text-zinc-950'
              }`}
            >
              🎬 Layout Templates
            </button>
          </div>
        </div>
      )}

      {/* PHASE: Upload (no media) */}
      {chatPhase === 'upload' && (
        <UploadPhase
          onPickFiles={() => fileInputRef.current?.click()}
          uploading={uploading}
          pastJobs={pastJobs}
          onPreviewReel={setActivePreviewUrl}
        />
      )}

      {/* Templates Mode View */}
      {chatPhase !== 'upload' && activeMode === 'templates' && (
        <div className="flex-1 overflow-y-auto px-5 pb-6 flex flex-col items-center">
          <div className="w-full max-w-5xl">
            {selectedTemplate ? (
              <TemplateEditor
                template={selectedTemplate}
                projectId={projectId || ''}
                mediaAssets={mediaAssets}
                onBack={() => setSelectedTemplate(null)}
                onRender={handleTemplateRender}
              />
            ) : (
              <TemplatePicker
                onSelect={(tmpl) => setSelectedTemplate(tmpl)}
                onClose={() => setActiveMode('ai')}
              />
            )}
          </div>
        </div>
      )}

      {/* PHASE: Chat (has media) */}
      {chatPhase !== 'upload' && activeMode === 'ai' && (
        <>
          {/* Scrollable chat area */}
          <div className="flex-1 overflow-y-auto custom-scroll w-full">
            <div className="px-5 md:px-8 pb-4 pt-4 space-y-6 w-full max-w-[1600px] mx-auto">
              {/* Media grid — always pinned at top of chat */}
              <MediaGrid
                assets={mediaAssets}
                onDelete={deleteAsset}
                onAddMore={() => fileInputRef.current?.click()}
                locked={['song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase)}
                uploading={uploading}
              />

              {/* === Vibe question === */}
              {['vibe', 'music', 'song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
                <ChatQuestion
                  question="What vibe are you going for?"
                  answered={chatPhase !== 'vibe'}
                  answeredValue={vibeOptions.find(v => v.value === config.vibe)?.label}
                >
                  {chatPhase === 'vibe' && (
                    <div className="flex flex-wrap gap-2 mt-3">
                      {vibeOptions.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => handleVibeSelect(opt.value as ConfigState['vibe'])}
                          className="flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-white border border-surface-200 shadow-sm hover:border-orange-400 hover:shadow-md text-sm font-medium text-surface-800 transition-all duration-200 active:scale-95"
                        >
                          <span>{opt.icon}</span>
                          <span>{opt.label}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </ChatQuestion>
              )}

              {/* === Music question === */}
              {['music', 'song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && (
                <ChatQuestion
                  question="What about background music?"
                  answered={chatPhase !== 'music'}
                  answeredValue={musicModeOptions.find(m => m.value === config.musicMode)?.label}
                >
                  {chatPhase === 'music' && (
                    <div className="flex flex-col gap-2 mt-3">
                      {musicModeOptions.map(opt => (
                        <button
                          key={opt.value}
                          onClick={() => handleMusicSelect(opt.value as ConfigState['musicMode'])}
                          className="flex items-start gap-3 px-4 py-3 rounded-2xl bg-white border border-surface-200 shadow-sm hover:border-orange-400 hover:shadow-md text-left transition-all duration-200 active:scale-[0.98]"
                        >
                          <Volume2 className="w-4 h-4 text-orange-500 flex-shrink-0 mt-0.5" />
                          <div>
                            <span className="block text-sm font-medium text-surface-800">{opt.label}</span>
                            <span className="block text-xs text-surface-500 mt-0.5">{opt.description}</span>
                          </div>
                        </button>
                      ))}
                    </div>
                  )}
                </ChatQuestion>
              )}

              {/* === Custom Song Query question === */}
              {['song_query', 'processing', 'story', 'rendering', 'complete', 'failed'].includes(chatPhase) && config.musicMode === 'custom' && (
                <ChatQuestion
                  question="Which song or artist would you like to search for?"
                  answered={chatPhase !== 'song_query'}
                  answeredValue={config.songQuery}
                />
              )}

              {/* === Story review card === */}
              {['story', 'processing', 'rendering', 'complete', 'failed'].includes(chatPhase) && job?.story_summary && (
                <StoryCard
                  story={job.story_summary}
                  instruction={rewriteInstruction}
                  onInstructionChange={setRewriteInstruction}
                  editing={editingStory}
                  textareaRef={storyTextareaRef}
                  onEditToggle={() => {
                    setEditingStory(e => !e);
                    if (!editingStory) setTimeout(() => storyTextareaRef.current?.focus(), 50);
                  }}
                  onGenerate={handleConfirmStory}
                  onRegenerate={handleRegenerateStory}
                  confirming={confirming}
                  isRegenerating={isRegenerating}
                  readOnly={chatPhase !== 'story'}
                />
              )}

              {/* === Processing messages === */}
              {chatPhase === 'processing' && (
                <ProcessingBubble messages={analysisMessages} />
              )}
              {chatPhase === 'rendering' && (
                <ProcessingBubble messages={renderMessages} />
              )}

              {/* === Complete: video player === */}
              {chatPhase === 'complete' && job?.final_video_url && (
                <CompletedCard 
                  url={job.final_video_url} 
                  onReset={handleResetAll} 
                  onPreview={() => setActivePreviewUrl(job.final_video_url)} 
                />
              )}

              {/* === Failed === */}
              {chatPhase === 'failed' && (
                <FailedCard message={job?.error_message} onRetry={handleResetAll} />
              )}

              <div ref={chatEndRef} />
            </div>
          </div>

          {/* Bottom chat input bar */}
          <ChatInputBar
            phase={chatPhase}
            value={inputText}
            onChange={setInputText}
            onSend={
              chatPhase === 'song_query' ? handleSendSongQuery : () => {}
            }
            onAddFiles={() => fileInputRef.current?.click()}
          />
        </>
      )}

      {/* ── Theatre Mode Video Preview Overlay ── */}
      {activePreviewUrl && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-md animate-fade-in flex items-center justify-center p-4">
          <div className="relative flex flex-col md:flex-row items-center gap-6 max-h-[90vh]">
            {/* Close Button */}
            <button
              onClick={() => setActivePreviewUrl(null)}
              className="absolute -top-12 right-0 md:-top-10 md:-right-10 z-20 w-10 h-10 rounded-full bg-black/60 hover:bg-black/80 text-white flex items-center justify-center cursor-pointer transition-all active:scale-95"
            >
              <X className="w-5 h-5" />
            </button>

            {/* Video Box */}
            <div className="relative w-full max-w-sm aspect-[9/16] bg-slate-950 rounded-3xl overflow-hidden shadow-2xl border border-white/10 flex items-center justify-center">
              <video
                src={activePreviewUrl}
                autoPlay
                controls
                playsInline
                className="w-full h-full object-contain"
              />
            </div>

            {/* Action buttons panel */}
            <div className="flex flex-row md:flex-col items-center gap-4 bg-black/40 backdrop-blur-sm p-4 rounded-3xl border border-white/5 z-10">
              {/* Save / Download */}
              <button
                onClick={() => triggerDownload(activePreviewUrl)}
                className="flex flex-col items-center gap-1 text-white cursor-pointer hover:scale-105 transition-transform"
              >
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
                  <Download className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-medium opacity-80">Save</span>
              </button>

              {/* Caption */}
              <button className="flex flex-col items-center gap-1 text-white cursor-pointer hover:scale-105 transition-transform">
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
                  <MessageSquare className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-medium opacity-80">Caption</span>
              </button>

              {/* Edit / Scissors */}
              <button
                onClick={() => {
                  const url = activePreviewUrl;
                  setActivePreviewUrl(null);
                  setShowEditorUrl(url);
                }}
                className="flex flex-col items-center gap-1 text-white cursor-pointer hover:scale-105 transition-transform"
              >
                <div className="w-10 h-10 rounded-full bg-orange-500 flex items-center justify-center shadow-md">
                  <Scissors className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-medium opacity-80">Edit</span>
              </button>

              {/* Voice */}
              <button className="flex flex-col items-center gap-1 text-white cursor-pointer hover:scale-105 transition-transform">
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
                  <Mic className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-medium opacity-80">Voice</span>
              </button>

              {/* Music */}
              <button className="flex flex-col items-center gap-1 text-white cursor-pointer hover:scale-105 transition-transform">
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center">
                  <Music className="w-4 h-4" />
                </div>
                <span className="text-[10px] font-medium opacity-80">Music</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Video Editor Modal ── */}
      {showEditorUrl && (
        <VideoEditorModal
          url={showEditorUrl}
          onClose={() => setShowEditorUrl(null)}
          onDownload={() => triggerDownload(showEditorUrl)}
        />
      )}
    </div>
  );
}
