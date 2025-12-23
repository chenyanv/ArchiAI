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
  MarkerType,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"
import { motion } from "framer-motion"
import { Box, ChevronRight, Loader2 } from "lucide-react"
import { type Component, type ComponentEdge } from "@/lib/api"

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

const LAYOUT = { nodeW: 260, nodeH: 120, gapX: 40, gapY: 80, layerGap: 140, labelW: 140 }

// === Types ===

type LayerStyle = { label: string; color: string; bg: string }

type ComponentNodeData = {
  component: Component
  onClick: () => void
  isLoading: boolean
  index: number
  style: LayerStyle
}

type LabelNodeData = { label: string; color: string; count: number }

type GraphNode = Node<ComponentNodeData, "component"> | Node<LabelNodeData, "label">

// === Helpers ===

const toTitleCase = (s: string) => s.split("-").map(w => w[0]?.toUpperCase() + w.slice(1)).join(" ")

// Compute rank for each component based on flow edges (longest path algorithm)
function computeRanks(components: Component[], edges: ComponentEdge[]): Map<string, number> {
  const ids = new Set(components.map(c => c.component_id))
  const inEdges = new Map<string, string[]>()
  const outEdges = new Map<string, string[]>()

  // Build adjacency lists
  for (const id of ids) {
    inEdges.set(id, [])
    outEdges.set(id, [])
  }
  for (const e of edges) {
    if (ids.has(e.from_component) && ids.has(e.to_component)) {
      outEdges.get(e.from_component)!.push(e.to_component)
      inEdges.get(e.to_component)!.push(e.from_component)
    }
  }

  // Compute ranks using longest path (BFS from sources)
  const ranks = new Map<string, number>()
  const queue: string[] = []

  // Initialize: nodes with no incoming edges start at rank 0
  for (const id of ids) {
    if (inEdges.get(id)!.length === 0) {
      ranks.set(id, 0)
      queue.push(id)
    }
  }

  // If no sources found (cycle or disconnected), set all to rank 0
  if (queue.length === 0) {
    for (const id of ids) ranks.set(id, 0)
    return ranks
  }

  // Process in topological order
  while (queue.length > 0) {
    const curr = queue.shift()!
    const currRank = ranks.get(curr)!
    for (const next of outEdges.get(curr)!) {
      const newRank = currRank + 1
      if (!ranks.has(next) || ranks.get(next)! < newRank) {
        ranks.set(next, newRank)
        queue.push(next)
      }
    }
  }

  // Handle disconnected nodes (no edges) - put them at rank 0
  for (const id of ids) {
    if (!ranks.has(id)) ranks.set(id, 0)
  }

  return ranks
}

// Group components by computed rank
function groupByRank(components: Component[], ranks: Map<string, number>): Map<number, Component[]> {
  const groups = new Map<number, Component[]>()
  for (const c of components) {
    const rank = ranks.get(c.component_id) ?? 0
    if (!groups.has(rank)) groups.set(rank, [])
    groups.get(rank)!.push(c)
  }
  return groups
}

// Get color based on architecture_layer (for visual grouping)
function getLayerStyle(layer: string, layerIndex: Map<string, number>): { color: string; bg: string } {
  const idx = layerIndex.get(layer) ?? 0
  return COLORS[idx % COLORS.length]
}

// Build layer index for consistent coloring
function buildLayerIndex(components: Component[]): Map<string, number> {
  const layers: string[] = []
  for (const c of components) {
    const layer = c.architecture_layer || "other"
    if (!layers.includes(layer)) layers.push(layer)
  }
  return new Map(layers.map((l, i) => [l, i]))
}

// === Layout ===

function buildGraph(
  components: Component[],
  businessFlow: ComponentEdge[],
  onClick: (c: Component) => void,
  loadingId: string | null
): { nodes: GraphNode[]; edges: Edge[] } {
  if (components.length === 0) return { nodes: [], edges: [] }

  // Step 1: Compute ranks based on flow edges
  const ranks = computeRanks(components, businessFlow)
  const rankGroups = groupByRank(components, ranks)
  const layerIndex = buildLayerIndex(components)

  // Step 2: Build nodes by rank
  const nodes: GraphNode[] = []
  const componentIds = new Set(components.map(c => c.component_id))
  const sortedRanks = Array.from(rankGroups.keys()).sort((a, b) => a - b)

  let y = 0
  let globalIdx = 0

  for (const rank of sortedRanks) {
    const items = rankGroups.get(rank) || []
    if (!items.length) continue

    const cols = Math.min(3, items.length)
    const startX = 40

    // Add rank label
    const rankLabel = rank === 0 ? "Entry" : rank === sortedRanks[sortedRanks.length - 1] ? "Data" : `Layer ${rank}`
    nodes.push({
      id: `lbl-rank-${rank}`,
      type: "label",
      position: { x: 0, y },
      data: { label: rankLabel, color: "#71717a", count: items.length },
      draggable: false,
      selectable: false,
    } as Node<LabelNodeData, "label">)

    // Add component nodes (offset by label height)
    const labelHeight = 60
    items.forEach((c: Component, i: number) => {
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
          isLoading: loadingId === id,
          style: { label: toTitleCase(layer), ...style },
        },
      } as Node<ComponentNodeData, "component">)
    })

    y += labelHeight + Math.ceil(items.length / cols) * (LAYOUT.nodeH + LAYOUT.gapY) + LAYOUT.layerGap
  }

  // Step 3: Build edges from business_flow
  const edges: Edge[] = businessFlow
    .filter(e => componentIds.has(e.from_component) && componentIds.has(e.to_component))
    .map((e, i) => ({
      id: `flow-${i}`,
      source: e.from_component,
      target: e.to_component,
      type: "smoothstep",
      animated: true,
      label: e.label,
      labelStyle: { fontSize: 10, fill: "#71717a" },
      labelBgStyle: { fill: "#fafafa", fillOpacity: 0.9 },
      style: { stroke: "#a1a1aa", strokeWidth: 2 },
      markerEnd: { type: MarkerType.ArrowClosed, color: "#a1a1aa" },
    }))

  return { nodes, edges }
}

// === Node Components ===

function ComponentNode({ data }: NodeProps<Node<ComponentNodeData, "component">>) {
  const { component: c, onClick, isLoading, index, style } = data

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
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg shrink-0" style={{ backgroundColor: style.bg }}>
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" style={{ color: style.color }} /> : <Box className="w-4 h-4" style={{ color: style.color }} />}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm truncate">{c.module_name}</div>
            {c.directory && <div className="text-xs text-zinc-400 font-mono truncate mt-0.5">{c.directory}</div>}
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-400 shrink-0 mt-1" />
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

const nodeTypes = { component: ComponentNode, label: LabelNode }

// === Main Component ===

interface Props {
  components: Component[]
  businessFlow?: ComponentEdge[]
  onComponentClick: (c: Component) => void
  loadingId: string | null
}

export function ArchitectureGraph({ components, businessFlow = [], onComponentClick, loadingId }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState<GraphNode>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [visible, setVisible] = useState(0)

  // Progressive reveal
  useEffect(() => {
    setVisible(0)
    const t = setInterval(() => setVisible(v => v >= components.length ? (clearInterval(t), v) : v + 1), 100)
    return () => clearInterval(t)
  }, [components.length])

  // Update graph
  useEffect(() => {
    const { nodes: n, edges: e } = buildGraph(components.slice(0, visible), businessFlow, onComponentClick, loadingId)
    setNodes(n)
    setEdges(e)
  }, [components, visible, businessFlow, onComponentClick, loadingId, setNodes, setEdges])

  // Calculate height based on ranks
  const height = useMemo(() => {
    const ranks = computeRanks(components, businessFlow)
    const rankGroups = groupByRank(components, ranks)
    const labelHeight = 60
    let total = 100
    for (const items of rankGroups.values()) {
      total += labelHeight + Math.ceil(items.length / 3) * (LAYOUT.nodeH + LAYOUT.gapY) + LAYOUT.layerGap
    }
    return Math.max(500, total)
  }, [components, businessFlow])

  return (
    <div className="w-full rounded-xl border border-zinc-200 bg-zinc-50/50 overflow-hidden" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
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
