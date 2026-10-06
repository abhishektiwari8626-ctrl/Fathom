import React, { useState } from 'react';
import { Play, CheckCircle2, AlertTriangle, XCircle, RotateCcw, Filter, Clock, Coins, Layers } from 'lucide-react';
import { RunResponse } from '../types/api';

interface RunListProps {
  runs: RunResponse[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  isLoading: boolean;
}

export const RunList: React.FC<RunListProps> = ({
  runs,
  selectedRunId,
  onSelectRun,
  isLoading,
}) => {
  const [filter, setFilter] = useState<'all' | 'failed' | 'rewound'>('all');
  const [search, setSearch] = useState('');

  const filteredRuns = runs.filter((run) => {
    if (filter === 'failed' && run.status !== 'failed') return false;
    if (filter === 'rewound' && !run.has_rewinds) return false;
    if (search && !run.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="w-80 h-full bg-slate-900/90 border-r border-slate-800 flex flex-col backdrop-blur-md">
      {/* Header */}
      <div className="p-4 border-b border-slate-800">
        <div className="flex items-center gap-2 mb-3">
          <div className="p-1.5 rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20">
            <Layers className="w-4 h-4" />
          </div>
          <div>
            <h1 className="font-bold text-slate-100 text-sm">FATHOM</h1>
            <p className="text-[10px] text-slate-400">Agent Tracing & Visual Debugger</p>
          </div>
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Filter runs..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700/80 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500 transition-colors"
        />

        {/* Filter Pills */}
        <div className="flex items-center gap-1.5 mt-2.5">
          <button
            onClick={() => setFilter('all')}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              filter === 'all' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            All ({runs.length})
          </button>
          <button
            onClick={() => setFilter('failed')}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              filter === 'failed' ? 'bg-red-900/60 text-red-200 border border-red-700' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            Failed
          </button>
          <button
            onClick={() => setFilter('rewound')}
            className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
              filter === 'rewound' ? 'bg-purple-900/60 text-purple-200 border border-purple-700' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`}
          >
            Rewound
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {isLoading ? (
          <div className="p-8 text-center text-xs text-slate-500">Loading traces...</div>
        ) : filteredRuns.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-500">No matching runs found</div>
        ) : (
          filteredRuns.map((run) => {
            const isSelected = selectedRunId === run.id;
            return (
              <div
                key={run.id}
                onClick={() => onSelectRun(run.id)}
                className={`p-3 rounded-xl border transition-all cursor-pointer select-none ${
                  isSelected
                    ? 'bg-slate-800 border-sky-500/80 shadow-md shadow-sky-500/10'
                    : 'bg-slate-950/60 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900'
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                    run.status === 'completed' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                    run.status === 'failed' ? 'bg-red-950 text-red-400 border border-red-800' :
                    'bg-blue-950 text-blue-400 border border-blue-800'
                  }`}>
                    {run.status}
                  </span>
                  {run.has_rewinds && (
                    <span className="flex items-center gap-1 text-[10px] text-purple-400 bg-purple-950/80 px-1.5 py-0.5 rounded border border-purple-800">
                      <RotateCcw className="w-3 h-3" />
                      v2
                    </span>
                  )}
                </div>

                <h3 className="font-semibold text-slate-100 text-xs truncate" title={run.name}>
                  {run.name}
                </h3>

                <div className="flex items-center justify-between mt-2 pt-2 border-t border-slate-800/60 text-[11px] text-slate-400 font-mono">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    <span>{(run.total_latency_ms / 1000).toFixed(1)}s</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Coins className="w-3 h-3" />
                    <span>{run.total_tokens}</span>
                  </div>
                  <div className="text-[10px] bg-slate-800 px-1.5 rounded">
                    {run.span_count} steps
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
