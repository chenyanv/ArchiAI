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
  EdgeLabelRenderer,
  BaseEdge,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { motion } from "framer-motion"
import { Box, ChevronRight, Loader2, Info } from "lucide-react"
import { type Component, type ComponentEdge, type RankedGroup } from "@/lib/api"

// === Constants ===

const COLORS = [
  { color: "#059669", bg: "#d1fae5" },
  { color: "#2563eb", bg: "#dbeafe" },
  { color: "#7c3aed", bg: "#ede9fe" },
  { color: "#dc2626", bg: "#fee2e2" },
  { color: "#d97706", bg: "#fef3c7" },
  { color: "#0891b2", bg: "#cffafe" },
  { color: "#be185d", bg: "#fce7f3" },
  { color: "#4f46e5", bg: "#e0e7ff" },
]

const LAYOUT = { nodeW: 260, nodeH: 120, gapX: 140, gapY: 100, layerGap: 180, labelW: 140 }

// === Types ===

type LayerStyle = { label: string; color: string; bg: string }

type ComponentNodeData = {
  component: Component
  onClick: () => void
  onSemanticClick?: (e: React.MouseEvent) => void
  isLoading: boolean
  index: number
  style: LayerStyle
}

type LabelNodeData = { label: string; color: string; count: number }

type GraphNode = Node<ComponentNodeData, "component"> | Node<LabelNodeData, "label">

// === Helpers ===

const toTitleCase = (s: string) => s.split("-").map(w => w[0]?.toUpperCase() + w.slice(1)).join(" ")

// Get color based on architecture_layer (for visual grouping)
function getLayerStyle(layer: string, layerIndex: Map<string, number>): { color: string; bg: string } {
  const idx = layerIndex.get(layer) ?? 0
  return COLORS[idx % COLORS.length]
}

// Build layer index for consistent coloring
function buildLayerIndex(components: Component[]): Map<string, number> {
  const layerSet = new Set<string>()
  for (const c of components) {
    const layer = c.architecture_layer || "other"
    layerSet.add(layer)
  }
  const layers = Array.from(layerSet)
  return new Map(layers.map((l, i) => [l, i]))
}

// === Layout ===

function buildGraph(
  rankedGroups: RankedGroup[],
  businessFlow: ComponentEdge[],
  onClick: (c: Component) => void,
  onSemanticClick: (c: Component, e: React.MouseEvent) => void,
  loadingId: string | null
): { nodes: GraphNode[]; edges: Edge[] } {
  if (rankedGroups.length === 0) return { nodes: [], edges: [] }

  // Build layer index for colors from all components
  const allComponents = rankedGroups.flatMap(g => g.components)
  const layerIndex = buildLayerIndex(allComponents)
  const componentIds = new Set(allComponents.map(c => c.component_id))

  const nodes: GraphNode[] = []
  let y = 0
  let globalIdx = 0

  // Iterate over pre-grouped ranks from backend
  for (const group of rankedGroups) {
    const { rank, label, components } = group
    if (!components.length) continue

    const cols = Math.min(3, components.length)
    const startX = 40
    const labelHeight = 60

    // Add rank label (label comes from backend)
    nodes.push({
      id: `lbl-rank-${rank}`,
      type: "label",
      position: { x: 0, y },
      data: { label, color: "#71717a", count: components.length },
      draggable: false,
      selectable: false,
    } as Node<LabelNodeData, "label">)

    // Add component nodes (offset by label height)
    components.forEach((c: Component, i: number) => {
      const id = c.component_id
      const layer = c.architecture_layer || "other"
      const style = getLayerStyle(layer, layerIndex)

      nodes.push({
        id,
        type: "component",
        position: {
          x: startX + (i % cols) * (LAYOUT.nodeW + LAYOUT.gapX),
          y: y + labelHeight + Math.floor(i / cols) * (LAYOUT.nodeH + LAYOUT.gapY),
        },
        data: {
          component: c,
          index: globalIdx++,
          onClick: () => onClick(c),
          onSemanticClick: (e) => onSemanticClick(c, e),
          isLoading: loadingId === id,
          style: { label: toTitleCase(layer), ...style },
        },
      } as Node<ComponentNodeData, "component">)
    })

    y += labelHeight + Math.ceil(components.length / cols) * (LAYOUT.nodeH + LAYOUT.gapY) + LAYOUT.layerGap
  }

  // Build edges from business_flow with offset to avoid overlapping
  const validEdges = businessFlow.filter(e => componentIds.has(e.from_component) && componentIds.has(e.to_component))

  // Count edges per source/target to calculate offsets
  const sourceCount = new Map<string, number>()
  const targetCount = new Map<string, number>()
  validEdges.forEach(e => {
    sourceCount.set(e.from_component, (sourceCount.get(e.from_component) || 0) + 1)
    targetCount.set(e.to_component, (targetCount.get(e.to_component) || 0) + 1)
  })

  // Track current index per source/target for offset calculation
  const sourceIdx = new Map<string, number>()
  const targetIdx = new Map<string, number>()

  const edges: Edge[] = validEdges.map((e, i) => {
    const srcTotal = sourceCount.get(e.from_component) || 1
    const tgtTotal = targetCount.get(e.to_component) || 1
    const srcIdx = sourceIdx.get(e.from_component) || 0
    const tgtIdx = targetIdx.get(e.to_component) || 0
    sourceIdx.set(e.from_component, srcIdx + 1)
    targetIdx.set(e.to_component, tgtIdx + 1)

    // Calculate offset: center the edges, spread by 20px
    const offset = srcTotal > 1 || tgtTotal > 1
      ? (srcIdx - (srcTotal - 1) / 2) * 20
      : 0

    return {
      id: `flow-${i}`,
      source: e.from_component,
      target: e.to_component,
      type: "labeled",
      animated: true,
      label: e.label,
      style: { stroke: "#d1d5db", strokeWidth: 1.5, strokeDasharray: "4 2" },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#9ca3af" },
      data: { offset },
    }
  })

  return { nodes, edges }
}

// === Node Components ===

function ComponentNode({ data }: NodeProps<Node<ComponentNodeData, "component">>) {
  const { component: c, onClick, onSemanticClick, isLoading, index, style } = data
  const hasSemanticMetadata = !!c.semantic_metadata

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ delay: index * 0.08, duration: 0.3 }}
      className="cursor-pointer"
      onClick={onClick}
    >
      <Handle type="target" position={Position.Top} className="!bg-zinc-400 !w-2 !h-2 !opacity-0" />
      <div
        className={`px-4 py-3 rounded-xl border-2 bg-white shadow-md min-w-[220px] max-w-[260px] transition-all hover:shadow-lg hover:scale-[1.02] ${isLoading ? "opacity-70" : ""}`}
        style={{ borderColor: style.color }}
      >
        <div className="flex items-start gap-2">
          <div className="p-2 rounded-lg shrink-0" style={{ backgroundColor: style.bg }}>
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: style.color }} /> : <Box className="w-4 h-4" style={{ color: style.color }} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm" style={{ overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{c.module_name || c.component_id || '(unnamed)'}</div>
            {c.directory && <div className="text-xs text-zinc-400 font-mono mt-0.5" style={{ overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>{c.directory}</div>}
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {hasSemanticMetadata && onSemanticClick && (
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onSemanticClick(e)
                }}
                className="p-1 hover:bg-blue-50 rounded-lg transition-colors"
                title="View semantic information"
              >
                <Info className="w-4 h-4 text-blue-600" />
              </button>
            )}
            <ChevronRight className="w-4 h-4 text-zinc-400 mt-0.5" />
          </div>
        </div>
        <p className="text-xs text-zinc-600 mt-2 line-clamp-2">{c.business_signal}</p>
        <div className="flex items-center gap-1.5 mt-2">
          <div className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: style.bg, color: style.color }}>{c.confidence}</div>
          {c.leading_landmarks.length > 0 && <div className="text-[10px] text-zinc-400">{c.leading_landmarks.length} landmarks</div>}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-zinc-400 !w-2 !h-2 !opacity-0" />
    </motion.div>
  )
}

function LabelNode({ data }: NodeProps<Node<LabelNodeData, "label">>) {
  return (
    <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} className="flex items-center gap-2 px-3 py-1.5 rounded-lg" style={{ backgroundColor: `${data.color}15` }}>
      <div className="w-1 h-8 rounded-full" style={{ backgroundColor: data.color }} />
      <div>
        <div className="text-sm font-semibold" style={{ color: data.color }}>{data.label}</div>
        <div className="text-xs text-zinc-500">{data.count} components</div>
      </div>
    </motion.div>
  )
}

// Custom edge with hover-to-reveal label
function LabeledEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  label,
  markerEnd,
  style,
  data,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false)
  const edgeOffset = data?.offset as number || 0
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    offset: edgeOffset,
  })

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{ cursor: "pointer" }}
    >
      {/* Invisible wider path for easier hover detection */}
      <path
        d={edgePath}
        fill="none"
        strokeWidth={24}
        stroke="transparent"
        pointerEvents="stroke"
      />
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: hovered ? "#6366f1" : (style?.stroke as string),
          strokeWidth: hovered ? 2.5 : (style?.strokeWidth as number),
        }}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "none",
              zIndex: 1000,
              opacity: hovered ? 1 : 0,
              transition: "opacity 0.15s ease-in-out",
            }}
            className="nodrag nopan"
          >
            <div className="px-2 py-1 text-[10px] font-medium text-white bg-indigo-500 border border-indigo-600 rounded shadow-lg whitespace-nowrap">
              {label as string}
            </div>
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  )
}

const nodeTypes = { component: ComponentNode, label: LabelNode }
const edgeTypes = { labeled: LabeledEdge }

// === Main Component ===

interface Props {
  rankedGroups: RankedGroup[]
  businessFlow?: ComponentEdge[]
  onComponentClick: (c: Component) => void
  onComponentSemanticClick?: (c: Component) => void
  loadingId: string | null
}

export function ArchitectureGraph({ rankedGroups, businessFlow = [], onComponentClick, onComponentSemanticClick, loadingId }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])

  // OPTIMIZATION: Render all components immediately instead of progressive reveal with 100ms interval
  // Let framer-motion handle staggered animations (80ms per component via index*0.08 delay)
  // This eliminates the 5+ second UI delay for large repositories
  const memoizedGroups = useMemo(() => rankedGroups, [rankedGroups])

  // Update graph
  useEffect(() => {
    const handleSemanticClick = (c: Component, e: React.MouseEvent) => {
      if (onComponentSemanticClick) {
        e.stopPropagation()
        onComponentSemanticClick(c)
      }
    }
    const { nodes: n, edges: e } = buildGraph(memoizedGroups, businessFlow, onComponentClick, handleSemanticClick, loadingId)
    setNodes(n)
    setEdges(e)
  }, [memoizedGroups, businessFlow, onComponentClick, onComponentSemanticClick, loadingId, setNodes, setEdges])

  // Calculate height based on ranks (pre-grouped by backend)
  const height = useMemo(() => {
    const labelHeight = 60
    let total = 100
    for (const group of rankedGroups) {
      total += labelHeight + Math.ceil(group.components.length / 3) * (LAYOUT.nodeH + LAYOUT.gapY) + LAYOUT.layerGap
    }
    return Math.max(500, total)
  }, [rankedGroups])

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-zinc-50/50 overflow-hidden" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultViewport={{ x: 20, y: 20, zoom: 1 }}
        minZoom={0.3}
        maxZoom={1.5}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#e4e4e7" />
      </ReactFlow>
    </div>
  )
}
