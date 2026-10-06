import React, { useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { SpanNode } from './SpanNode';
import { DagResponse, SpanResponse } from '../types/api';
import { transformDagToReactFlow } from '../utils/dagTransform';
import { AlertTriangle, Sparkles } from 'lucide-react';

interface DagCanvasProps {
  dag: DagResponse;
  selectedSpanId: string | null;
  onSelectSpan: (span: SpanResponse) => void;
}

export const DagCanvas: React.FC<DagCanvasProps> = ({
  dag,
  selectedSpanId,
  onSelectSpan,
}) => {
  const nodeTypes = useMemo(() => ({ spanNode: SpanNode }), []);

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => transformDagToReactFlow(dag, selectedSpanId, onSelectSpan),
    [dag, selectedSpanId, onSelectSpan]
  );

  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className="relative w-full h-full bg-slate-950">
      {/* Root Cause Banner (F-01) */}
      {dag.root_cause && (
        <div className="absolute top-4 left-4 z-10 max-w-md p-3 rounded-xl bg-red-950/80 border border-red-800/80 shadow-xl backdrop-blur-md flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
          <div className="text-xs">
            <span className="font-bold text-red-200">Root Cause Detected:</span>
            <p className="text-red-300 mt-0.5 leading-relaxed">{dag.root_cause.explanation}</p>
          </div>
        </div>
      )}

      {/* Legend overlay */}
      <div className="absolute bottom-4 left-4 z-10 p-3 rounded-xl bg-slate-900/80 border border-slate-800/80 shadow-lg backdrop-blur-md flex items-center gap-4 text-[11px] text-slate-300">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
          <span>Pass</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
          <span>Warning</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-red-500" />
          <span>Failure</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
          <span>Rewound Branch</span>
        </div>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        minZoom={0.2}
        maxZoom={1.5}
        className="bg-slate-950"
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#334155" />
        <Controls className="!bg-slate-900 !border-slate-800 !fill-slate-200 [&>button]:!border-slate-800 [&>button]:!bg-slate-900 [&>button:hover]:!bg-slate-800" />
        <MiniMap
          nodeColor={(node: any) => {
            const span = node.data?.span;
            if (span?.status === 'failed' || span?.effective_verdict === 'failure') return '#ef4444';
            if (span?.effective_verdict === 'warning') return '#f59e0b';
            if (span?.status === 'rewound') return '#a855f7';
            return '#10b981';
          }}
          className="!bg-slate-900/90 !border-slate-800 !rounded-xl"
        />
      </ReactFlow>
    </div>
  );
};
