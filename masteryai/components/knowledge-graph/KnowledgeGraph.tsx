'use client'

import { useCallback, useEffect } from 'react'
import ReactFlow, {
  Node,
  Edge,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  MarkerType,
  BackgroundVariant,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { KnowledgeNode } from '@/lib/types'

interface Props {
  nodes: KnowledgeNode[]
}

function buildGraphLayout(nodes: KnowledgeNode[]): { flowNodes: Node[]; flowEdges: Edge[] } {
  const cols = 3
  const nodeWidth = 200
  const nodeHeight = 80
  const hGap = 60
  const vGap = 40

  const flowNodes: Node[] = nodes.map((n, i) => {
    const col = i % cols
    const row = Math.floor(i / cols)
    return {
      id: n.id,
      position: {
        x: col * (nodeWidth + hGap),
        y: row * (nodeHeight + vGap),
      },
      data: { label: n.skill_name, completed: n.is_completed },
      type: 'default',
      style: {
        background: n.is_completed
          ? 'linear-gradient(135deg, #10b981, #059669)'
          : 'linear-gradient(135deg, #7c3aed, #4f46e5)',
        color: '#fff',
        border: 'none',
        borderRadius: '12px',
        padding: '10px 16px',
        fontSize: '13px',
        fontWeight: '600',
        width: nodeWidth,
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      },
    }
  })

  const nodesByName = Object.fromEntries(nodes.map(n => [n.skill_name, n.id]))
  const flowEdges: Edge[] = []

  nodes.forEach(n => {
    if (n.dependencies) {
      ;(n.dependencies as string[]).forEach(dep => {
        const sourceId = nodesByName[dep]
        if (sourceId) {
          flowEdges.push({
            id: `${sourceId}-${n.id}`,
            source: sourceId,
            target: n.id,
            animated: !n.is_completed,
            markerEnd: { type: MarkerType.ArrowClosed, color: '#7c3aed' },
            style: { stroke: '#7c3aed', strokeWidth: 2 },
          })
        }
      })
    }
  })

  return { flowNodes, flowEdges }
}

export function KnowledgeGraph({ nodes }: Props) {
  const { flowNodes, flowEdges } = buildGraphLayout(nodes)
  const [rfNodes, setNodes, onNodesChange] = useNodesState(flowNodes)
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState(flowEdges)

  const onConnect = useCallback(
    (params: Connection) => setEdges(eds => addEdge(params, eds)),
    [setEdges]
  )

  if (nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        No skills mapped yet. Generate a roadmap to see your knowledge graph.
      </div>
    )
  }

  return (
    <div style={{ height: '600px' }} className="rounded-xl overflow-hidden border border-gray-200 dark:border-gray-700">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
        attributionPosition="bottom-right"
      >
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#374151" />
        <Controls className="!bg-white dark:!bg-gray-900 !border-gray-200 dark:!border-gray-700" />
        <MiniMap
          style={{ background: '#1f2937' }}
          nodeColor={n => (n.data?.completed ? '#10b981' : '#7c3aed')}
        />
      </ReactFlow>
    </div>
  )
}
