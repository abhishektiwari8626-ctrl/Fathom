import React from 'react';
import { Code2, Sparkles } from 'lucide-react';

interface ModeToggleProps {
  isDevMode: boolean;
  onToggle: (devMode: boolean) => void;
}

export const ModeToggle: React.FC<ModeToggleProps> = ({ isDevMode, onToggle }) => {
  return (
    <div className="flex items-center bg-slate-900 border border-slate-700 p-1 rounded-xl shadow-inner">
      <button
        onClick={() => onToggle(false)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          !isDevMode
            ? 'bg-sky-600 text-white shadow-sm'
            : 'text-slate-400 hover:text-slate-200'
        }`}
      >
        <Sparkles className="w-3.5 h-3.5" />
        <span>Non-Developer</span>
      </button>
      <button
        onClick={() => onToggle(true)}
        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
          isDevMode
            ? 'bg-indigo-600 text-white shadow-sm'
            : 'text-slate-400 hover:text-slate-200'
        }`}
      >
        <Code2 className="w-3.5 h-3.5" />
        <span>Developer</span>
      </button>
    </div>
  );
};
