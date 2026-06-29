import { Plus, Send } from 'lucide-react';

type ChatPhase =
  | 'upload'
  | 'vibe'
  | 'music'
  | 'song_query'
  | 'processing'
  | 'story'
  | 'rendering'
  | 'complete'
  | 'failed';

interface ChatInputBarProps {
  phase: ChatPhase;
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onAddFiles: () => void;
}

export default function ChatInputBar({
  phase,
  value,
  onChange,
  onSend,
  onAddFiles,
}: ChatInputBarProps) {
  const getPlaceholder = () => {
    if (phase === 'song_query') return 'Type your song or artist...';
    if (phase === 'story') return 'Type to edit...';
    if (phase === 'complete') return 'Ask for changes...';
    return 'Message...';
  };

  const isDisabled = ['processing', 'rendering', 'complete', 'failed'].includes(phase);

  return (
    <div className="px-4 pb-4 pt-2 flex items-center gap-2.5 border-t border-surface-200/50 bg-transparent">
      {/* Add files button */}
      <button
        onClick={onAddFiles}
        disabled={isDisabled}
        className="w-9 h-9 rounded-full bg-white shadow-sm border border-surface-200 flex items-center justify-center flex-shrink-0 hover:border-orange-400 disabled:opacity-40 transition-all"
      >
        <Plus className="w-4 h-4 text-surface-600" />
      </button>

      {/* Text input */}
      <div className="flex-1 bg-white rounded-full shadow-sm border border-surface-200 px-4 py-2.5">
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && value.trim()) onSend(); }}
          placeholder={getPlaceholder()}
          disabled={isDisabled}
          className="w-full text-sm text-surface-800 placeholder:text-surface-400 bg-transparent focus:outline-none disabled:opacity-40"
        />
      </div>

      {/* Send button */}
      <button
        onClick={onSend}
        disabled={isDisabled || !value.trim()}
        className="w-9 h-9 rounded-full bg-white shadow-sm border border-surface-200 flex items-center justify-center flex-shrink-0 hover:border-orange-400 hover:bg-orange-50 disabled:opacity-40 transition-all"
      >
        <Send className="w-4 h-4 text-surface-600" />
      </button>
    </div>
  );
}
