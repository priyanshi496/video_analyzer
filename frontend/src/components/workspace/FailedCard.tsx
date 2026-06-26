import { RotateCcw } from 'lucide-react';

interface FailedCardProps {
  message?: string | null;
  onRetry: () => void;
}

export default function FailedCard({ message, onRetry }: FailedCardProps) {
  return (
    <div className="animate-slide-up flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-4 max-w-[85%] space-y-3">
        <p className="text-sm font-medium text-error-600">Something went wrong</p>
        {message && <p className="text-xs text-surface-500">{message}</p>}
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 px-4 py-2 bg-surface-900 text-white rounded-full text-sm font-medium hover:bg-surface-700 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          Try again
        </button>
      </div>
    </div>
  );
}
