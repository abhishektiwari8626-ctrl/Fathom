import dagre from 'dagre';
import { Node, Edge, MarkerType } from '@xyflow/react';
import { DagResponse, SpanResponse } from '../types/api';

const NODE_WIDTH = 280;
const NODE_HEIGHT = 100;

export interface DagNodeData extends Record<string, unknown> {
  span: SpanResponse;
  isRootCause: boolean;
  rootCauseType?: 'originating' | 'propagated' | null;
  onSelect: (span: SpanResponse) => void;
  isSelected: boolean;
}

export function transformDagToReactFlow(
  dag: DagResponse,
  selectedSpanId: string | null,
  onSelectSpan: (span: SpanResponse) => void
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 50, ranksep: 70 });
  g.setDefaultEdgeLabel(() => ({}));

  // 1. Add nodes to Dagre
  dag.spans.forEach((span) => {
    g.setNode(span.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });

  // 2. Add parent-child edges to Dagre
  dag.spans.forEach((span) => {
    if (span.parent_span_id) {
      g.setEdge(span.parent_span_id, span.id);
    }
  });

  // 3. Compute layout
  dagre.layout(g);

  // 4. Construct React Flow nodes
  const nodes: Node[] = dag.spans.map((span) => {
    const nodeWithPos = g.node(span.id);
    const x = nodeWithPos ? nodeWithPos.x - NODE_WIDTH / 2 : 0;
    const y = nodeWithPos ? nodeWithPos.y - NODE_HEIGHT / 2 : 0;

    const isRootCause = Boolean(
      span.is_root_cause || (dag.root_cause && dag.root_cause.span_id === span.id)
    );

    return {
      id: span.id,
      type: 'spanNode',
      position: { x, y },
      data: {
        span,
        isRootCause,
        rootCauseType: span.root_cause_type,
        onSelect: onSelectSpan,
        isSelected: selectedSpanId === span.id,
      } as DagNodeData,
    };
  });

  // 5. Construct React Flow edges
  const edges: Edge[] = [];

  // Direct parent-child causal links (Solid)
  dag.spans.forEach((span) => {
    if (span.parent_span_id) {
      const isRunning = span.status === 'running';
      const isFailing = span.status === 'failed' || span.effective_verdict === 'failure';

      edges.push({
        id: `e-${span.parent_span_id}-${span.id}`,
        source: span.parent_span_id,
        target: span.id,
        animated: isRunning,
        style: {
          stroke: isFailing ? '#ef4444' : isRunning ? '#38bdf8' : '#475569',
          strokeWidth: isFailing ? 2.5 : 2,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isFailing ? '#ef4444' : isRunning ? '#38bdf8' : '#64748b',
        },
      });
    }
  });

  // Data-flow edges from span_links (Dashed)
  if (dag.links && Array.isArray(dag.links)) {
    dag.links.forEach((link) => {
      edges.push({
        id: `link-${link.from_span_id}-${link.to_span_id}`,
        source: link.from_span_id,
        target: link.to_span_id,
        style: {
          stroke: '#94a3b8',
          strokeDasharray: '5,5',
          strokeWidth: 1.5,
        },
        markerEnd: {
          type: MarkerType.Arrow,
          color: '#94a3b8',
        },
      });
    });
  }

  return { nodes, edges };
}
