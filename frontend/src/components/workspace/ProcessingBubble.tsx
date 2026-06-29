import { useState, useEffect } from 'react';

interface ProcessingBubbleProps {
  messages: string[];
}

export default function ProcessingBubble({ messages }: ProcessingBubbleProps) {
  const [msgIndex, setMsgIndex] = useState(0);
  const [visible, setVisible] = useState(true);

  // Reset index when message list changes
  useEffect(() => {
    setMsgIndex(0);
  }, [messages]);

  useEffect(() => {
    const interval = setInterval(() => {
      setVisible(false);
      setTimeout(() => {
        setMsgIndex(i => (i + 1) % messages.length);
        setVisible(true);
      }, 350);
    }, 2500);
    return () => clearInterval(interval);
  }, [messages]);

  return (
    <div className="animate-slide-up space-y-2 flex flex-col items-start w-full">
      <div className="bg-white rounded-2xl rounded-tl-sm shadow-sm px-4 py-2.5 max-w-[85%] border border-surface-200/60">
        <p
          className={`text-[15px] font-medium text-orange-600 transition-opacity duration-300 ${visible ? 'opacity-100' : 'opacity-0'}`}
          style={{ fontStyle: 'italic' }}
        >
          {messages[msgIndex]}
        </p>
      </div>
      <p className="text-xs text-surface-400 pl-1">
        might take a couple of minutes
        <br />
        you can leave and come back later
      </p>
    </div>
  );
}
