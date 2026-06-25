interface ProgressBarProps {
  progress: number;
  className?: string;
  showLabel?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

export function ProgressBar({ progress, className = '', showLabel = true, size = 'md' }: ProgressBarProps) {
  const clampedProgress = Math.min(100, Math.max(0, progress));
  const sizeStyles = {
    sm: 'h-1.5',
    md: 'h-2.5',
    lg: 'h-4',
  };

  return (
    <div className={`w-full ${className}`}>
      <div className={`w-full bg-surface-200 rounded-full overflow-hidden ${sizeStyles[size]}`}>
        <div
          className={`
            h-full bg-gradient-to-r from-primary-500 to-primary-400
            rounded-full transition-all duration-700 ease-out
            relative overflow-hidden
          `}
          style={{ width: `${clampedProgress}%` }}
        >
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" />
        </div>
      </div>
      {showLabel && (
        <div className="flex justify-between items-center mt-1.5">
          <span className="text-xs text-surface-500 font-medium">{clampedProgress.toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
}
