import React, { useState, useEffect } from 'react';
import { 
  X, Copy, Check, RotateCcw, AlertTriangle, CheckCircle2, XCircle, 
  Sparkles, Code2, Clock, Coins, ShieldAlert, FileText, ChevronRight 
} from 'lucide-react';
import axios from 'axios';
import { SpanResponse, EvaluationResponse, RewindResponse } from '../types/api';

interface NodeInspectorProps {
  span: SpanResponse | null;
  runId: string;
  isDevMode: boolean;
  onClose: () => void;
  onRewindSuccess: () => void;
}

export const NodeInspector: React.FC<NodeInspectorProps> = ({
  span,
  runId,
  isDevMode,
  onClose,
  onRewindSuccess,
}) => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [editedInputJson, setEditedInputJson] = useState<string>('');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [isRewinding, setIsRewinding] = useState(false);
  const [rewindMessage, setRewindMessage] = useState<string | null>(null);

  useEffect(() => {
    if (span) {
      setEditedInputJson(JSON.stringify(span.input_data || {}, null, 2));
      setJsonError(null);
      setRewindMessage(null);
    }
  }, [span]);

  if (!span) return null;

  const handleCopy = (key: string, data: any) => {
    navigator.clipboard.writeText(typeof data === 'string' ? data : JSON.stringify(data, null, 2));
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const handleInputChange = (val: string) => {
    setEditedInputJson(val);
    try {
      JSON.parse(val);
      setJsonError(null);
    } catch (e: any) {
      setJsonError(e.message);
    }
  };

  const handleRewind = async () => {
    if (jsonError) return;
    let parsedInput: Record<string, any>;
    try {
      parsedInput = JSON.parse(editedInputJson);
    } catch {
      setJsonError("Invalid JSON payload");
      return;
    }

    setIsRewinding(true);
    setRewindMessage(null);
    try {
      const res = await axios.post<RewindResponse>(`/api/v1/runs/${runId}/rewind`, {
        span_id: span.id,
        mutated_input: parsedInput,
        re_execute: true,
      });

      if (res.data.success) {
        setRewindMessage(res.data.message);
        setTimeout(() => {
          onRewindSuccess();
        }, 800);
      }
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || "Failed to rewind span";
      setRewindMessage(`Error: ${msg}`);
    } finally {
      setIsRewinding(false);
    }
  };

  // Find Phase 3 Judge evaluation
  const judgeEval = span.evaluations?.find(e => e.phase === 'judge_llm');
  const toolEval = span.evaluations?.find(e => e.phase === 'tool_check');
  const driftEval = span.evaluations?.find(e => e.phase === 'semantic_drift');

  const reasoning = judgeEval?.details?.reasoning || span.error_message;
  const suggestedFix = judgeEval?.details?.suggested_fix;

  return (
    <div className="fixed right-0 top-0 bottom-0 w-[480px] bg-slate-900/95 border-l border-slate-700/80 shadow-2xl backdrop-blur-xl flex flex-col z-50 animate-in slide-in-from-right duration-300">
      {/* Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase font-mono tracking-wider text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
              {span.kind}
            </span>
            {span.effective_verdict && (
              <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${
                span.effective_verdict === 'pass' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                span.effective_verdict === 'warning' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                'bg-red-950 text-red-400 border border-red-800'
              }`}>
                {span.effective_verdict}
              </span>
            )}
          </div>
          <h2 className="text-base font-bold text-slate-100 mt-1 truncate" title={span.name}>
            {span.name}
          </h2>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          <X className="w-5 h-5" />
        </button>
      </div>

      {/* Content scroll area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs text-slate-300">
        {/* NON-DEVELOPER VIEW */}
        {!isDevMode ? (
          <div className="space-y-4">
            {/* Verdict Card */}
            <div className={`p-4 rounded-xl border ${
              span.effective_verdict === 'pass' ? 'bg-emerald-950/30 border-emerald-800/80 text-emerald-200' :
              span.effective_verdict === 'warning' ? 'bg-amber-950/30 border-amber-800/80 text-amber-200' :
              'bg-red-950/30 border-red-800/80 text-red-200'
            }`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2 font-semibold text-sm">
                  {span.effective_verdict === 'pass' ? <CheckCircle2 className="w-5 h-5 text-emerald-400" /> :
                   span.effective_verdict === 'warning' ? <AlertTriangle className="w-5 h-5 text-amber-400" /> :
                   <XCircle className="w-5 h-5 text-red-400" />}
                  <span>Step Evaluation: {span.effective_verdict?.toUpperCase() || 'EVALUATED'}</span>
                </div>
                <span className="text-[10px] bg-slate-900/60 px-2 py-0.5 rounded text-slate-400 font-mono">
                  AI-Generated
                </span>
              </div>
              <p className="text-xs text-slate-300 leading-relaxed">
                {judgeEval?.summary || "This step finished execution without critical alerts."}
              </p>
            </div>

            {/* Why It Matters */}
            {reasoning && (
              <div className="bg-slate-800/50 p-3.5 rounded-xl border border-slate-700/60 space-y-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5" />
                  Why It Matters
                </span>
                <p className="text-xs text-slate-200 leading-relaxed font-sans">{reasoning}</p>
              </div>
            )}

            {/* Suggested Fix */}
            {suggestedFix && (
              <div className="bg-amber-950/20 p-3.5 rounded-xl border border-amber-800/50 space-y-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5" />
                  Suggested Action
                </span>
                <p className="text-xs text-amber-200 leading-relaxed font-sans">{suggestedFix}</p>
              </div>
            )}
          </div>
        ) : (
          /* DEVELOPER VIEW */
          <div className="space-y-4">
            {/* Quick Metrics Grid */}
            <div className="grid grid-cols-2 gap-2 text-slate-300">
              <div className="bg-slate-800/60 border border-slate-700/50 p-2.5 rounded-lg">
                <div className="flex items-center gap-1.5 text-slate-400 mb-1">
                  <Clock className="w-3.5 h-3.5" />
                  <span className="text-[11px]">Latency</span>
                </div>
                <span className="text-sm font-bold text-slate-100 font-mono">{span.latency_ms.toFixed(1)} ms</span>
              </div>
              <div className="bg-slate-800/60 border border-slate-700/50 p-2.5 rounded-lg">
                <div className="flex items-center gap-1.5 text-slate-400 mb-1">
                  <Coins className="w-3.5 h-3.5" />
                  <span className="text-[11px]">Tokens</span>
                </div>
                <span className="text-sm font-bold text-slate-100 font-mono">{span.token_count}</span>
              </div>
            </div>

            {/* Phase Diagnostics */}
            <div className="bg-slate-800/40 border border-slate-700/60 p-3 rounded-xl space-y-2">
              <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                Evaluation Diagnostics
              </span>
              {toolEval && (
                <div className="flex items-center justify-between text-xs py-1 border-b border-slate-800">
                  <span className="text-slate-400">Phase 1 (Tool Check):</span>
                  <span className="font-mono text-emerald-400">HTTP {toolEval.details?.http_status || 200}</span>
                </div>
              )}
              {driftEval && (
                <div className="flex items-center justify-between text-xs py-1 border-b border-slate-800">
                  <span className="text-slate-400">Phase 2 (Cosine Similarity):</span>
                  <span className="font-mono text-sky-400">{driftEval.score?.toFixed(3) || 'N/A'}</span>
                </div>
              )}
              {judgeEval && (
                <div className="flex items-center justify-between text-xs py-1">
                  <span className="text-slate-400">Phase 3 Model:</span>
                  <span className="font-mono text-indigo-400">{judgeEval.details?.judge_model || 'gpt-4o-mini'}</span>
                </div>
              )}
            </div>

            {/* Raw JSON Inputs & Outputs */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Input Payload</span>
                <button
                  onClick={() => handleCopy('input', span.input_data)}
                  className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200"
                >
                  {copiedKey === 'input' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>Copy</span>
                </button>
              </div>
              <pre className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg font-mono text-[11px] overflow-x-auto text-slate-300 max-h-40">
                {JSON.stringify(span.input_data, null, 2)}
              </pre>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Output Payload</span>
                <button
                  onClick={() => handleCopy('output', span.output_data)}
                  className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-200"
                >
                  {copiedKey === 'output' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>Copy</span>
                </button>
              </div>
              <pre className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg font-mono text-[11px] overflow-x-auto text-slate-300 max-h-40">
                {JSON.stringify(span.output_data, null, 2)}
              </pre>
            </div>

            {span.error_message && (
              <div className="space-y-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-red-400">Stack Trace</span>
                <pre className="p-2.5 bg-red-950/30 border border-red-800/60 rounded-lg font-mono text-[11px] text-red-300 overflow-x-auto max-h-36">
                  {span.error_message}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* TIME-TRAVEL REWIND SECTION (Section 10.5 & 18 U-04) */}
        <div className="mt-6 pt-4 border-t border-slate-800 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
              <RotateCcw className="w-4 h-4 text-purple-400" />
              Time-Travel Mutation Editor
            </span>
            <span className="text-[10px] text-slate-400">Fix & Re-execute Downstream</span>
          </div>

          <p className="text-[11px] text-slate-400">
            Edit the parameters below. When submitted, Fathom branches the execution and re-runs all dependent steps without modifying past history.
          </p>

          <textarea
            value={editedInputJson}
            onChange={(e) => handleInputChange(e.target.value)}
            rows={5}
            className={`w-full p-2.5 rounded-lg bg-slate-950 font-mono text-xs text-slate-200 border transition-colors focus:outline-none ${
              jsonError ? 'border-red-500 focus:border-red-400' : 'border-slate-700 focus:border-purple-500'
            }`}
          />

          {jsonError && (
            <p className="text-[11px] text-red-400 font-mono">
              Syntax error: {jsonError}
            </p>
          )}

          {rewindMessage && (
            <div className={`p-2.5 rounded-lg text-xs ${
              rewindMessage.startsWith('Error') ? 'bg-red-950/40 text-red-300 border border-red-800' : 'bg-emerald-950/40 text-emerald-300 border border-emerald-800'
            }`}>
              {rewindMessage}
            </div>
          )}

          <button
            onClick={handleRewind}
            disabled={isRewinding || Boolean(jsonError)}
            className="w-full py-2.5 px-4 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-xs flex items-center justify-center gap-2 shadow-lg shadow-purple-600/30 transition-all"
          >
            {isRewinding ? (
              <>
                <RotateCcw className="w-4 h-4 animate-spin" />
                <span>Re-executing Downstream Steps...</span>
              </>
            ) : (
              <>
                <RotateCcw className="w-4 h-4" />
                <span>Rewind & Re-Run From Here</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
