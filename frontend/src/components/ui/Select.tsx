import { type SelectHTMLAttributes, forwardRef } from 'react';
import { ChevronDown } from 'lucide-react';

interface SelectOption {
  value: string;
  label: string;
  icon?: string;
  description?: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: SelectOption[];
  error?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  ({ className = '', label, options, error, ...props }, ref) => {
    return (
      <div className="w-full">
        {label && (
          <label className="block text-sm font-medium text-surface-700 mb-1.5">
            {label}
          </label>
        )}
        <div className="relative">
          <select
            ref={ref}
            className={`
              w-full px-4 py-2.5 pr-10
              bg-white border border-surface-200 rounded-xl
              text-surface-900
              focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500
              transition-all duration-200
              appearance-none cursor-pointer
              ${error ? 'border-error-500 focus:ring-error-500/20 focus:border-error-500' : ''}
              ${className}
            `}
            {...props}
          >
            {options.map(option => (
              <option key={option.value} value={option.value}>
                {option.icon ? `${option.icon} ` : ''}{option.label}
              </option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" />
        </div>
        {error && <p className="mt-1 text-sm text-error-500">{error}</p>}
      </div>
    );
  }
);

Select.displayName = 'Select';
