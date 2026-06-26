import { type TextareaHTMLAttributes, forwardRef } from 'react';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className = '', label, error, ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-surface-700 mb-1.5">
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          className={`
            w-full px-4 py-3
            bg-white border border-surface-200 rounded-xl
            text-surface-900 placeholder:text-surface-400
            focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500
            transition-all duration-200
            resize-none min-h-[120px]
            ${error ? 'border-error-500 focus:ring-error-500/20 focus:border-error-500' : ''}
            ${className}
          `}
          {...props}
        />
        {error && <p className="mt-1 text-sm text-error-500">{error}</p>}
      </div>
    );
  }
);

Textarea.displayName = 'Textarea';
