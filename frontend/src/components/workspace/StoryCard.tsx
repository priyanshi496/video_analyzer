import React from 'react';
import { Pencil, Volume2 } from 'lucide-react';

interface StoryCardProps {
  story: string;
  instruction: string;
  onInstructionChange: (v: string) => void;
  editing: boolean;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
  onEditToggle: () => void;
  onGenerate: () => void;
  confirming: boolean;
  readOnly?: boolean;
}

export default function StoryCard({
  story,
  instruction,
  onInstructionChange,
  editing,
  textareaRef,
  onEditToggle,
  onGenerate,
  confirming,
  readOnly,
}: StoryCardProps) {
  return (
    <div className="animate-slide-up space-y-3 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm overflow-hidden max-w-[92%] border border-surface-200/60">
        <div className="p-4">
          <p className="text-sm text-surface-800 leading-relaxed">{story}</p>

          {editing && !readOnly && (
            <div className="mt-4 pt-4 border-t border-surface-100">
              <textarea
                ref={textareaRef}
                value={instruction}
                onChange={e => onInstructionChange(e.target.value)}
                placeholder="Ask AI to make changes (e.g., make it shorter, more emotional...)"
                rows={3}
                className="w-full text-sm text-surface-800 leading-relaxed resize-none focus:outline-none bg-transparent"
              />
            </div>
          )}

          {!editing && !readOnly && (
            <button
              onClick={onEditToggle}
              className="flex items-center gap-1.5 mt-3 text-xs text-orange-500 hover:text-orange-600 transition-colors font-medium"
            >
              <Pencil className="w-3 h-3" />
              Ask AI to change story
            </button>
          )}
        </div>

        {!readOnly && (
          <div className="border-t border-surface-100 px-4 py-2.5 flex items-center gap-2 text-xs text-surface-400">
            <Volume2 className="w-3.5 h-3.5" />
            <span>this story will guide your video's narrative</span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      {!readOnly && (
        <div className="flex items-center gap-3 pl-1">
          <button
            onClick={onGenerate}
            disabled={confirming}
            className="flex items-center gap-2 px-5 py-2.5 bg-orange-600 text-white rounded-full text-sm font-semibold shadow-sm hover:bg-orange-700 disabled:opacity-60 transition-all duration-200 active:scale-95"
          >
            {confirming && <div className="w-3.5 h-3.5 border border-white/40 border-t-white rounded-full animate-spin" />}
            {editing && instruction.trim() ? 'Rewrite & Generate' : 'Generate'}
          </button>
        </div>
      )}
    </div>
  );
}
