"use client"

import { useEffect, useMemo, useState } from "react"
import {
  ReactFlow,
  Node,
  Edge,
  useNodesState,
  useEdgesState,
  Background,
  BackgroundVariant,
  Position,
  Handle,
  type NodeProps,
  type EdgeProps,
  MarkerType,
  getSmoothStepPath,
  BaseEdge,
  EdgeLabelRenderer,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { motion } from "framer-motion"
import { FileCode, FolderOpen, Box, Workflow, Database, Globe, Cpu, ChevronRight, Loader2, Search, Code2, Info, ArrowRight } from "lucide-react"
import { type NavigationNode, type NodeRelationship, type DrilldownResponse, type Component } from "@/lib/api"

// === Constants ===

const RELATIONSHIP_TYPE_STYLES: Record<string, { color: string; dashArray: string }> = {
  calls: { color: "#dc2626", dashArray: "4 2" },        // Red - direct invocation
  contains: { color: "#7c3aed", dashArray: "6 3" },     // Purple - structural
  uses: { color: "#0891b2", dashArray: "5 2" },         // Cyan - dependency
  depends_on: { color: "#d97706", dashArray: "7 2" },   // Orange - runtime
  triggers: { color: "#be185d", dashArray: "3 3" },     // Pink - event
  returns_to: { color: "#059669", dashArray: "8 2" },   // Green - async
}

const NODE_TYPE_STYLES: Record<string, { color: string; bg: string; Icon: typeof Box }> = {
  file: { color: "#2563eb", bg: "#dbeafe", Icon: FileCode },
  directory: { color: "#7c3aed", bg: "#ede9fe", Icon: FolderOpen },
  module: { color: "#059669", bg: "#d1fae5", Icon: Box },
  function: { color: "#dc2626", bg: "#fee2e2", Icon: Workflow },
  class: { color: "#d97706", bg: "#fef3c7", Icon: Database },
  endpoint: { color: "#0891b2", bg: "#cffafe", Icon: Globe },
  service: { color: "#be185d", bg: "#fce7f3", Icon: Cpu },
  workflow: { color: "#4f46e5", bg: "#e0e7ff", Icon: Workflow },
  capability: { color: "#059669", bg: "#d1fae5", Icon: Box },
  category: { color: "#7c3aed", bg: "#ede9fe", Icon: FolderOpen },
  default: { color: "#71717a", bg: "#f4f4f5", Icon: Box },
}

const LAYOUT = { nodeW: 420, baseH: 80, gapX: 40, gapY: 50, seqGapY: 60 }

// Estimate node height based on description length
function estimateNodeHeight(description: string): number {
  // Node width is 420, minus padding (40px) and icon area (50px) = ~330px for text
  // At ~7px per char for 14px font, that's ~47 chars per line
  const charsPerLine = 45
  const lines = Math.ceil(description.length / charsPerLine)
  const lineHeight = 22 // text-sm with leading-relaxed
  return LAYOUT.baseH + Math.max(0, lines - 1) * lineHeight
}

// === Types ===

type DrilldownNodeData = {
  node: NavigationNode
  onClick: () => void
  onSemanticClick?: (e: React.MouseEvent) => void
  isLoading: boolean
  index: number
  style: { color: string; bg: string; Icon: typeof Box }
  isSequential: boolean
  isLast: boolean
}

type GraphNode = Node<DrilldownNodeData, "drilldown">

// === Helpers ===

function getNodeStyle(nodeType: string): { color: string; bg: string; Icon: typeof Box } {
  return NODE_TYPE_STYLES[nodeType] || NODE_TYPE_STYLES.default
}

// === Layout ===

function buildGraph(
  nodes: NavigationNode[],
  relationships: NodeRelationship[] | undefined,
  isSequential: boolean,
  onClick: (node: NavigationNode) => void,
  onSemanticClick: (node: NavigationNode, e: React.MouseEvent) => void,
  loadingId: string | null
): { nodes: GraphNode[]; edges: Edge[] } {
  if (nodes.length === 0) return { nodes: [], edges: [] }

  const graphNodes: GraphNode[] = []
  const edges: Edge[] = []

  // If relationships exist, use relationship-based layout, otherwise use sequential/grid
  const hasRelationships = relationships && relationships.length > 0

  if (hasRelationships) {
    // Relationship graph layout - compute positions using simple hierarchical layout
    const nodeHeights = new Map<string, number>(nodes.map(n => [n.node_key, estimateNodeHeight(n.description)]))

    // Build adjacency for layout algorithm
    const inDegree = new Map<string, number>()
    const outDegree = new Map<string, number>()
    nodes.forEach(n => {
      inDegree.set(n.node_key, 0)
      outDegree.set(n.node_key, 0)
    })

    relationships.forEach(rel => {
      outDegree.set(rel.from_node_key, (outDegree.get(rel.from_node_key) || 0) + 1)
      inDegree.set(rel.to_node_key, (inDegree.get(rel.to_node_key) || 0) + 1)
    })

    // Simple hierarchical layout: root nodes on left, progressively to right
    const levels = new Map<string, number>()
    const visited = new Set<string>()

    function assignLevel(nodeKey: string, level: number) {
      if (visited.has(nodeKey)) return
      visited.add(nodeKey)
      levels.set(nodeKey, Math.max(levels.get(nodeKey) || 0, level))

      relationships?.forEach(rel => {
        if (rel.from_node_key === nodeKey) {
          assignLevel(rel.to_node_key, level + 1)
        }
      })
    }

    // Start from nodes with no incoming edges
    nodes.forEach(n => {
      if (!inDegree.has(n.node_key) || inDegree.get(n.node_key) === 0) {
        assignLevel(n.node_key, 0)
      }
    })

    // For remaining unassigned nodes, assign them
    nodes.forEach(n => {
      if (!levels.has(n.node_key)) {
        assignLevel(n.node_key, 0)
      }
    })

    // Group nodes by level
    const levelGroups = new Map<number, NavigationNode[]>()
    nodes.forEach(n => {
      const level = levels.get(n.node_key) || 0
      if (!levelGroups.has(level)) levelGroups.set(level, [])
      levelGroups.get(level)!.push(n)
    })

    // Position nodes
    levelGroups.forEach((nodesAtLevel, level) => {
      const x = level * 500 + 40
      let y = 40

      nodesAtLevel.forEach((node) => {
        const height = nodeHeights.get(node.node_key) || 80
        const style = getNodeStyle(node.node_type)

        graphNodes.push({
          id: node.node_key,
          type: "drilldown",
          position: { x, y },
          data: {
            node,
            onClick: () => onClick(node),
            onSemanticClick: (e) => onSemanticClick(node, e),
            isLoading: loadingId === node.node_key,
            index: nodes.indexOf(node),
            style,
            isSequential: false,
            isLast: false,
          },
        } as GraphNode)

        y += height + LAYOUT.gapY
      })
    })

    // Add relationship edges with type-based styling
    relationships.forEach((rel, idx) => {
      const relStyle = RELATIONSHIP_TYPE_STYLES[rel.relationship_type] || RELATIONSHIP_TYPE_STYLES.calls
      edges.push({
        id: `rel-${idx}`,
        source: rel.from_node_key,
        target: rel.to_node_key,
        type: "smoothstep",
        animated: true,
        label: rel.flow_label,
        style: {
          stroke: relStyle.color,
          strokeWidth: 1.5,
          strokeDasharray: relStyle.dashArray
        },
        markerEnd: { type: MarkerType.ArrowClosed, color: relStyle.color },
      })
    })
  } else if (isSequential) {
    // Vertical sequential layout with dynamic heights
    let y = 40
    nodes.forEach((node, i) => {
      const style = getNodeStyle(node.node_type)
      const nodeHeight = estimateNodeHeight(node.description)

      graphNodes.push({
        id: node.node_key,
        type: "drilldown",
        position: { x: 40, y },
        data: {
          node,
          onClick: () => onClick(node),
          onSemanticClick: (e) => onSemanticClick(node, e),
          isLoading: loadingId === node.node_key,
          index: i,
          style,
          isSequential: true,
          isLast: i === nodes.length - 1,
        },
      } as GraphNode)

      // Add edge to next node
      if (i < nodes.length - 1) {
        edges.push({
          id: `edge-${i}`,
          source: node.node_key,
          target: nodes[i + 1].node_key,
          type: "smoothstep",
          animated: true,
          style: { stroke: "#d1d5db", strokeWidth: 2 },
          markerEnd: { type: MarkerType.ArrowClosed, color: "#9ca3af" },
        })
      }

      y += nodeHeight + LAYOUT.seqGapY
    })
  } else {
    // Grid layout - single column with dynamic heights
    let y = 40
    nodes.forEach((node, i) => {
      const style = getNodeStyle(node.node_type)
      const nodeHeight = estimateNodeHeight(node.description)

      graphNodes.push({
        id: node.node_key,
        type: "drilldown",
        position: { x: 40, y },
        data: {
          node,
          onClick: () => onClick(node),
          onSemanticClick: (e) => onSemanticClick(node, e),
          isLoading: loadingId === node.node_key,
          index: i,
          style,
          isSequential: false,
          isLast: false,
        },
      } as GraphNode)

      y += nodeHeight + LAYOUT.gapY
    })
  }

  return { nodes: graphNodes, edges }
}

// === Node Component ===

function DrilldownNode({ data }: NodeProps<Node<DrilldownNodeData, "drilldown">>) {
  const { node, onClick, onSemanticClick, isLoading, index, style, isSequential, isLast } = data
  const Icon = style.Icon
  const isInspect = node.action_kind === "inspect_source"
  const hasSemanticMetadata = !!node.semantic_metadata

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.25 }}
      className="cursor-pointer"
      onClick={onClick}
    >
      {isSequential && <Handle type="target" position={Position.Top} className="!bg-zinc-400 !w-2 !h-2 !opacity-0" />}

      <div
        className={`px-5 py-4 rounded-xl border-2 bg-white shadow-md transition-all hover:shadow-lg hover:scale-[1.02] ${isLoading ? "opacity-70" : ""}`}
        style={{ borderColor: style.color, width: LAYOUT.nodeW }}
      >
        <div className="flex items-start gap-3">
          {/* Sequence number for sequential mode */}
          {isSequential && (
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-base font-bold shrink-0"
              style={{ backgroundColor: style.bg, color: style.color }}
            >
              {(node.sequence_order ?? index) + 1}
            </div>
          )}

          {/* Icon */}
          {!isSequential && (
            <div className="p-2.5 rounded-lg shrink-0" style={{ backgroundColor: style.bg }}>
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" style={{ color: style.color }} />
              ) : (
                <Icon className="w-5 h-5" style={{ color: style.color }} />
              )}
            </div>
          )}

          {/* Content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <div className="font-semibold text-base">{node.title}</div>
              {/* Action badge */}
              <div
                className="text-xs px-2 py-0.5 rounded font-medium shrink-0 flex items-center gap-1"
                style={{
                  backgroundColor: isInspect ? "#dbeafe" : "#d1fae5",
                  color: isInspect ? "#2563eb" : "#059669"
                }}
              >
                {isInspect ? <Code2 className="w-3.5 h-3.5" /> : <Search className="w-3.5 h-3.5" />}
                {isInspect ? "Source" : "Drill"}
              </div>
            </div>
            <p className="text-sm text-zinc-600 mt-2 leading-relaxed">{node.description}</p>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 shrink-0">
            {hasSemanticMetadata && onSemanticClick && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onSemanticClick(e)
                }}
                className="p-1.5 hover:bg-blue-50 rounded-lg transition-colors"
                title="View semantic information"
              >
                <Info className="w-4 h-4 text-blue-600" />
              </button>
            )}
            <ChevronRight className="w-5 h-5 text-zinc-400 mt-1" />
          </div>
        </div>
      </div>

      {isSequential && !isLast && (
        <Handle type="source" position={Position.Bottom} className="!bg-zinc-400 !w-2 !h-2 !opacity-0" />
      )}
    </motion.div>
  )
}

const nodeTypes = { drilldown: DrilldownNode }

// === Main Component ===

interface Props {
  response: DrilldownResponse
  componentCard: Component
  onNodeClick: (node: NavigationNode, componentCard: Component, cacheId: string) => void
  onSemanticClick?: (node: NavigationNode) => void
  loadingId: string | null
}

export function DrilldownGraph({ response, componentCard, onNodeClick, onSemanticClick, loadingId }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // OPTIMIZATION: Render all nodes immediately instead of 80ms progressive reveal
  // Let framer-motion handle staggered animations (60ms per node via index*0.06 delay)
  // This eliminates 1.6 second UI delay for 20-node drilldowns
  const memoizedNodes = useMemo(() => response.nodes, [response.nodes])

  // Build graph
  useEffect(() => {
    const handleClick = (node: NavigationNode) => {
      onNodeClick(node, componentCard, response.cache_id)
    }
    const handleSemanticClick = (node: NavigationNode, e: React.MouseEvent) => {
      if (onSemanticClick) {
        e.stopPropagation()
        onSemanticClick(node)
      }
    }
    const { nodes: n, edges: e } = buildGraph(memoizedNodes, response.relationships, response.is_sequential, handleClick, handleSemanticClick, loadingId)
    setNodes(n)
    setEdges(e)
  }, [memoizedNodes, response.relationships, response.is_sequential, response.cache_id, componentCard, onNodeClick, onSemanticClick, loadingId, setNodes, setEdges])

  // Calculate height based on actual node heights
  const height = useMemo(() => {
    if (response.nodes.length === 0) return 400

    // For relationship graph, add extra width for horizontal layout
    const hasRelationships = response.relationships && response.relationships.length > 0
    if (hasRelationships) {
      return Math.max(600, response.nodes.length * 150)
    }

    const gap = response.is_sequential ? LAYOUT.seqGapY : LAYOUT.gapY
    const totalHeight = response.nodes.reduce((sum, node) =>
      sum + estimateNodeHeight(node.description) + gap, 0)
    return Math.max(400, totalHeight + 80)
  }, [response.nodes, response.relationships, response.is_sequential])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 text-sm text-zinc-500 mb-2">
          <span>{componentCard.module_name}</span>
          {response.focus_label && (
            <>
              <ChevronRight className="w-3 h-3" />
              <span className="text-zinc-900">{response.focus_label}</span>
            </>
          )}
        </div>
        <h1 className="text-xl font-bold">{response.agent_goal}</h1>
        <p className="text-zinc-600 mt-1 text-sm">{response.rationale}</p>
      </div>

      {/* Graph canvas */}
      <div className="w-full rounded-xl border border-zinc-200 bg-zinc-50/50 overflow-hidden" style={{ height }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          defaultViewport={{ x: 0, y: 0, zoom: 1 }}
          minZoom={0.5}
          maxZoom={1.5}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
        >
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e4e4e7" />
        </ReactFlow>
      </div>

      {/* Notes section */}
      {response.nodes.length > 0 && (
        <div className="text-xs text-zinc-500">
          {response.nodes.length} items · {response.is_sequential ? "Sequential flow" : "Related components"}
        </div>
      )}
    </div>
  )
}
