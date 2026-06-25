import { type InputHTMLAttributes, forwardRef } from 'react';
import { Check } from 'lucide-react';

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string;
  checked?: boolean;
  onChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className = '', label, checked, onChange, ...props }, ref) => {
    return (
      <label className="inline-flex items-center gap-3 cursor-pointer group">
        <div className="relative">
          <input
            ref={ref}
            type="checkbox"
            className="sr-only peer"
            checked={checked}
            onChange={onChange}
            {...props}
          />
          <div
            className={`
              w-5 h-5 rounded-md border-2
              flex items-center justify-center
              transition-all duration-200
              peer-checked:bg-primary-500 peer-checked:border-primary-500
              border-surface-300 group-hover:border-primary-400
              ${className}
            `}
          >
            <Check
              className={`
                w-3 h-3 text-white
                transition-all duration-200
                ${checked ? 'scale-100 opacity-100' : 'scale-50 opacity-0'}
              `}
              strokeWidth={3}
            />
          </div>
        </div>
        {label && (
          <span className="text-sm text-surface-700 select-none">{label}</span>
        )}
      </label>
    );
  }
);

Checkbox.displayName = 'Checkbox';
