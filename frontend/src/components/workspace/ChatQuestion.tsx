import React from 'react';
import { Check } from 'lucide-react';

interface ChatQuestionProps {
  question: string;
  answered: boolean;
  answeredValue?: string;
  children?: React.ReactNode;
}

export default function ChatQuestion({
  question,
  answered,
  answeredValue,
  children,
}: ChatQuestionProps) {
  return (
    <div className="animate-slide-up flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-3.5 max-w-[85%] md:max-w-2xl border border-surface-200/60">
        <p className="text-sm text-surface-800 leading-relaxed">{question}</p>
        {answered && answeredValue && (
          <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 bg-orange-50 rounded-full">
            <Check className="w-3 h-3 text-orange-500" strokeWidth={3} />
            <span className="text-xs font-medium text-orange-600">{answeredValue}</span>
          </div>
        )}
        {!answered && children && (
          <div className="mt-4">
            {children}
          </div>
        )}
      </div>
    </div>
  );
}
