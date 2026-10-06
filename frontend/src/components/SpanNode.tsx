import React from 'react';
import { Handle, Position } from '@xyflow/react';
import { CheckCircle2, AlertTriangle, XCircle, RotateCcw, Loader2, Sparkles, Database, Wrench, Cpu, Compass } from 'lucide-react';
import { DagNodeData } from '../utils/dagTransform';
import { SpanKind, EvaluationVerdict, SpanStatus } from '../types/api';

const KIND_CONFIG: Record<SpanKind, { label: string; bg: string; text: string; icon: any }> = {
  llm_call: { label: 'LLM Call', bg: 'bg-indigo-900/60 border-indigo-700', text: 'text-indigo-300', icon: Sparkles },
  tool_call: { label: 'Tool Call', bg: 'bg-emerald-900/60 border-emerald-700', text: 'text-emerald-300', icon: Wrench },
  retrieval: { label: 'Retrieval', bg: 'bg-sky-900/60 border-sky-700', text: 'text-sky-300', icon: Database },
  processing: { label: 'Processing', bg: 'bg-slate-800 border-slate-600', text: 'text-slate-300', icon: Cpu },
  agent_decision: { label: 'Decision', bg: 'bg-fuchsia-900/60 border-fuchsia-700', text: 'text-fuchsia-300', icon: Compass },
};

export const SpanNode: React.FC<{ data: DagNodeData }> = ({ data }) => {
  const { span, isRootCause, isSelected, onSelect } = data;
  const kindConfig = KIND_CONFIG[span.kind] || KIND_CONFIG.processing;
  const KindIcon = kindConfig.icon;

  // Determine border & badge styles based on effective verdict & status
  let borderStyle = 'border-slate-700 hover:border-slate-500';
  let VerdictIcon = CheckCircle2;
  let verdictColor = 'text-emerald-400';

  if (span.status === 'running') {
    borderStyle = 'border-blue-500 shadow-lg shadow-blue-500/20 animate-pulse';
    VerdictIcon = Loader2;
    verdictColor = 'text-blue-400 animate-spin';
  } else if (span.status === 'failed' || span.effective_verdict === 'failure') {
    borderStyle = 'border-red-500 shadow-lg shadow-red-500/20 bg-red-950/20';
    VerdictIcon = XCircle;
    verdictColor = 'text-red-400';
  } else if (span.effective_verdict === 'warning') {
    borderStyle = 'border-amber-500 shadow-lg shadow-amber-500/20 bg-amber-950/20';
    VerdictIcon = AlertTriangle;
    verdictColor = 'text-amber-400';
  } else if (span.status === 'rewound') {
    borderStyle = 'border-purple-500/80 border-dashed bg-purple-950/20 opacity-80';
    VerdictIcon = RotateCcw;
    verdictColor = 'text-purple-400';
  } else if (span.status === 'pending') {
    borderStyle = 'border-slate-500 border-dashed bg-slate-900/50';
    VerdictIcon = Loader2;
    verdictColor = 'text-slate-400';
  } else {
    borderStyle = 'border-emerald-500/80 shadow-sm shadow-emerald-500/10';
    VerdictIcon = CheckCircle2;
    verdictColor = 'text-emerald-400';
  }

  if (isSelected) {
    borderStyle += ' ring-2 ring-sky-400 ring-offset-2 ring-offset-slate-950';
  }

  return (
    <div
      onClick={() => onSelect(span)}
      className={`relative w-[280px] rounded-xl border bg-slate-900/90 backdrop-blur-md p-3.5 transition-all duration-200 cursor-pointer select-none ${borderStyle}`}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-400 !w-2.5 !h-2.5" />

      {/* Root Cause Banner (F-01, U-08) */}
      {isRootCause && (
        <div className="absolute -top-3 left-3 bg-red-600 text-white text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full flex items-center gap-1 shadow-md shadow-red-600/40 animate-bounce">
          <AlertTriangle className="w-3 h-3" />
          Likely Root Cause
        </div>
      )}

      {/* Rewind Generation Tag */}
      {span.rewind_depth && span.rewind_depth > 0 ? (
        <div className="absolute -top-2.5 right-3 bg-purple-600 text-white text-[9px] font-semibold px-1.5 py-0.5 rounded">
          Branch v{span.rewind_depth}
        </div>
      ) : null}

      {/* Header: Kind Badge & Status Icon */}
      <div className="flex items-center justify-between mb-2">
        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-medium ${kindConfig.bg} ${kindConfig.text}`}>
          <KindIcon className="w-3 h-3" />
          <span>{kindConfig.label}</span>
        </div>
        <div className="flex items-center gap-1">
          <VerdictIcon className={`w-4 h-4 ${verdictColor}`} />
        </div>
      </div>

      {/* Span Name */}
      <h3 className="font-semibold text-slate-100 text-sm truncate" title={span.name}>
        {span.name}
      </h3>

      {/* Footer Meta: Latency & Tokens */}
      <div className="mt-2.5 pt-2 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-400 font-mono">
        <span>{span.latency_ms.toFixed(0)} ms</span>
        {span.token_count > 0 && <span>{span.token_count} tok</span>}
        {span.effective_verdict && (
          <span className={`uppercase font-sans font-bold text-[9px] px-1 rounded ${
            span.effective_verdict === 'pass' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
            span.effective_verdict === 'warning' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
            'bg-red-950 text-red-400 border border-red-800'
          }`}>
            {span.effective_verdict}
          </span>
        )}
      </div>

      <Handle type="source" position={Position.Bottom} className="!bg-slate-400 !w-2.5 !h-2.5" />
    </div>
  );
};
