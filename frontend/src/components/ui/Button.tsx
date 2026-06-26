import { type ButtonHTMLAttributes, forwardRef } from 'react';
import { Loader2 } from 'lucide-react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
}

const variantStyles: Record<ButtonVariant, string> = {
  primary: 'bg-gradient-to-r from-primary-500 to-primary-600 text-white hover:from-primary-600 hover:to-primary-700 shadow-lg shadow-primary-500/25 hover:shadow-xl hover:shadow-primary-500/30',
  secondary: 'bg-white text-surface-700 hover:bg-surface-50 border border-surface-200 shadow-sm hover:shadow-md',
  ghost: 'bg-transparent text-surface-600 hover:bg-surface-100',
  danger: 'bg-error-500 text-white hover:bg-error-600 shadow-lg shadow-error-500/25',
};

const sizeStyles: Record<ButtonSize, string> = {
  sm: 'text-sm px-3 py-1.5 gap-1.5',
  md: 'text-sm px-4 py-2.5 gap-2',
  lg: 'text-base px-6 py-3 gap-2',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = '', variant = 'primary', size = 'md', loading, icon, disabled, children, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={`
          inline-flex items-center justify-center font-medium rounded-xl
          transition-all duration-200 ease-out
          focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500/50
          disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none
          active:scale-[0.98]
          ${variantStyles[variant]}
          ${sizeStyles[size]}
          ${className}
        `}
        disabled={disabled || loading}
        {...props}
      >
        {loading ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : icon ? (
          <span className="flex-shrink-0">{icon}</span>
        ) : null}
        {children}
      </button>
    );
  }
);

Button.displayName = 'Button';
