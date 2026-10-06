import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { RunList } from './components/RunList';
import { DagCanvas } from './components/DagCanvas';
import { NodeInspector } from './components/NodeInspector';
import { ModeToggle } from './components/ModeToggle';
import { RunResponse, DagResponse, SpanResponse } from './types/api';
import { RotateCcw, AlertCircle, RefreshCw } from 'lucide-react';

export function App() {
  const [runs, setRuns] = useState<RunResponse[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [dag, setDag] = useState<DagResponse | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<SpanResponse | null>(null);
  const [isDevMode, setIsDevMode] = useState<boolean>(true);
  const [isLoadingRuns, setIsLoadingRuns] = useState<boolean>(true);
  const [isLoadingDag, setIsLoadingDag] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch all runs
  const fetchRuns = useCallback(async () => {
    try {
      setIsLoadingRuns(true);
      setError(null);
      const res = await axios.get<RunResponse[]>('/api/v1/runs');
      setRuns(res.data);
      if (res.data.length > 0 && !selectedRunId) {
        // Default to first run or first failed run
        const preferred = res.data.find(r => r.status === 'failed') || res.data[0];
        setSelectedRunId(preferred.id);
      }
    } catch (err: any) {
      console.error('Failed to load runs:', err);
      setError('Could not connect to Fathom backend. Please ensure the server is running on port 8000.');
    } finally {
      setIsLoadingRuns(false);
    }
  }, [selectedRunId]);

  // Fetch DAG for selected run
  const fetchDag = useCallback(async (runId: string) => {
    try {
      setIsLoadingDag(true);
      setError(null);
      const res = await axios.get<DagResponse>(`/api/v1/runs/${runId}/dag`);
      setDag(res.data);

      // Keep currently selected span in sync if it still exists
      setSelectedSpan(prev => {
        if (!prev) return null;
        return res.data.spans.find(s => s.id === prev.id) || null;
      });
    } catch (err: any) {
      console.error('Failed to load DAG:', err);
      setError(`Failed to load graph for run ${runId}`);
    } finally {
      setIsLoadingDag(false);
    }
  }, []);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  useEffect(() => {
    if (selectedRunId) {
      fetchDag(selectedRunId);
    }
  }, [selectedRunId, fetchDag]);

  const handleRewindSuccess = () => {
    fetchRuns();
    if (selectedRunId) {
      fetchDag(selectedRunId);
    }
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 font-sans text-slate-100">
      {/* Sidebar: Run List */}
      <RunList
        runs={runs}
        selectedRunId={selectedRunId}
        onSelectRun={(id) => {
          setSelectedRunId(id);
          setSelectedSpan(null);
        }}
        isLoading={isLoadingRuns}
      />

      {/* Main Graph Viewport */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Top Navbar */}
        <header className="h-14 border-b border-slate-800 bg-slate-900/80 px-6 flex items-center justify-between backdrop-blur-md z-20">
          <div className="flex items-center gap-3">
            {dag ? (
              <>
                <h2 className="font-bold text-slate-100 text-sm">{dag.run.name}</h2>
                <span className={`text-[10px] uppercase font-bold px-2 py-0.5 rounded ${
                  dag.run.status === 'completed' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                  dag.run.status === 'failed' ? 'bg-red-950 text-red-400 border border-red-800' :
                  'bg-blue-950 text-blue-400 border border-blue-800'
                }`}>
                  {dag.run.status}
                </span>
                {dag.run.has_rewinds && (
                  <span className="flex items-center gap-1 text-[10px] text-purple-400 bg-purple-950/80 px-2 py-0.5 rounded border border-purple-800">
                    <RotateCcw className="w-3 h-3" />
                    Rewound Branch Active
                  </span>
                )}
              </>
            ) : (
              <span className="text-xs text-slate-400">Select a run from the sidebar</span>
            )}
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={() => {
                if (selectedRunId) fetchDag(selectedRunId);
                fetchRuns();
              }}
              title="Refresh Graph"
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <ModeToggle isDevMode={isDevMode} onToggle={setIsDevMode} />
          </div>
        </header>

        {/* Graph Canvas Area */}
        <div className="flex-1 relative overflow-hidden">
          {error ? (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/90 z-30 p-6">
              <div className="max-w-md p-6 rounded-2xl bg-red-950/40 border border-red-800/80 text-center space-y-3">
                <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
                <h3 className="font-bold text-sm text-red-200">Connection Error</h3>
                <p className="text-xs text-red-300 leading-relaxed">{error}</p>
                <button
                  onClick={fetchRuns}
                  className="px-4 py-2 bg-red-800/60 hover:bg-red-700/60 text-white rounded-lg text-xs font-semibold"
                >
                  Retry Connection
                </button>
              </div>
            </div>
          ) : isLoadingDag ? (
            <div className="flex items-center justify-center h-full text-xs text-slate-400">
              Loading causal graph...
            </div>
          ) : dag ? (
            <DagCanvas
              dag={dag}
              selectedSpanId={selectedSpan ? selectedSpan.id : null}
              onSelectSpan={setSelectedSpan}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-xs text-slate-500">
              No trace run selected. Choose a run from the left panel.
            </div>
          )}
        </div>
      </div>

      {/* Right Drawer: Node Inspector */}
      {selectedSpan && selectedRunId && (
        <NodeInspector
          span={selectedSpan}
          runId={selectedRunId}
          isDevMode={isDevMode}
          onClose={() => setSelectedSpan(null)}
          onRewindSuccess={handleRewindSuccess}
        />
      )}
    </div>
  );
}
export default App;
