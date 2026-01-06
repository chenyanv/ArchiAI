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
import dagre from "dagre"

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

const LAYOUT = { nodeW: 500, baseH: 90, gapX: 40, gapY: 50, seqGapY: 60 }

// Estimate node height based on description length
function estimateNodeHeight(description: string): number {
  // Node width is 500, minus padding (40px) and icon area (50px) = ~410px for text
  // At ~7px per char for 14px font, that's ~58 chars per line
  const charsPerLine = 54
  const lines = Math.ceil(description.length / charsPerLine)
  const lineHeight = 20 // text-sm with leading-relaxed
  // Add buffer space for better breathing room
  return LAYOUT.baseH + Math.max(0, lines - 1) * lineHeight + 12
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
    // Relationship graph layout - compute positions using Dagre automatic layout
    const dagreGraph = new dagre.graphlib.Graph({ compound: false })

    // Configure graph layout algorithm
    dagreGraph.setGraph({
      rankdir: "LR", // Left to right direction
      nodesep: 180, // Horizontal separation between nodes (increased for no overlap)
      ranksep: 450, // Vertical separation between ranks (increased for taller nodes)
      marginx: 60,
      marginy: 60,
    })

    dagreGraph.setDefaultEdgeLabel(() => ({}))

    // Add nodes to Dagre graph with calculated dimensions
    nodes.forEach(node => {
      const height = estimateNodeHeight(node.description)
      dagreGraph.setNode(node.node_key, {
        width: LAYOUT.nodeW,
        height: height,
      })
    })

    // Add edges to Dagre graph
    relationships.forEach((rel) => {
      dagreGraph.setEdge(rel.from_node_key, rel.to_node_key)
    })

    // Run Dagre layout algorithm
    dagre.layout(dagreGraph)

    // Extract positions from Dagre and create React Flow nodes
    dagreGraph.nodes().forEach((nodeId) => {
      const node = nodes.find(n => n.node_key === nodeId)
      if (!node) return

      const dagreNode = dagreGraph.node(nodeId)
      const style = getNodeStyle(node.node_type)

      // Dagre returns center coordinates, adjust for top-left origin
      // React Flow uses top-left origin, so subtract half width/height
      const x = dagreNode.x - dagreNode.width / 2
      const y = dagreNode.y - dagreNode.height / 2

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
    let y = 60
    nodes.forEach((node, i) => {
      const style = getNodeStyle(node.node_type)
      const nodeHeight = estimateNodeHeight(node.description)

      graphNodes.push({
        id: node.node_key,
        type: "drilldown",
        position: { x: 60, y },
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

      // Increased spacing to accommodate larger nodes
      y += nodeHeight + 90
    })
  } else {
    // Grid layout - single column with dynamic heights
    let y = 60
    nodes.forEach((node, i) => {
      const style = getNodeStyle(node.node_type)
      const nodeHeight = estimateNodeHeight(node.description)

      graphNodes.push({
        id: node.node_key,
        type: "drilldown",
        position: { x: 60, y },
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

      // Increased spacing to accommodate larger nodes
      y += nodeHeight + 70
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
