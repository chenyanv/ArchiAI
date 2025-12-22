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

const toTitleCase = (s: string) => s.split("-").map(w => w[0].toUpperCase() + w.slice(1)).join(" ")

function getLayerStyle(layer: string, index: number): LayerStyle {
  const c = COLORS[index % COLORS.length]
  return { label: toTitleCase(layer), color: c.color, bg: c.bg }
}

function groupComponents(components: Component[]) {
  const layers: string[] = []
  const groups = new Map<string, Component[]>()

  for (const c of components) {
    const layer = c.architecture_layer || "other"
    if (!groups.has(layer)) {
      layers.push(layer)
      groups.set(layer, [])
    }
    groups.get(layer)!.push(c)
  }

  return { layers, groups }
}

// === Layout ===

function buildGraph(
  components: Component[],
  businessFlow: ComponentEdge[],
  onClick: (c: Component) => void,
  loadingId: string | null
): { nodes: GraphNode[]; edges: Edge[] } {
  const { layers, groups } = groupComponents(components)
  const nodes: GraphNode[] = []
  const componentIds = new Set(components.map(c => c.component_id))

  let y = 0, globalIdx = 0

  for (let li = 0; li < layers.length; li++) {
    const layer = layers[li]
    const items = groups.get(layer) || []
    if (!items.length) continue

    const style = getLayerStyle(layer, li)
    const cols = Math.min(3, items.length)
    const startX = LAYOUT.labelW + 40

    // Layer label
    nodes.push({
      id: `lbl-${layer}`,
      type: "label",
      position: { x: 0, y: y + 30 },
      data: { label: style.label, color: style.color, count: items.length },
      draggable: false,
      selectable: false,
    } as Node<LabelNodeData, "label">)

    // Component nodes
    items.forEach((c, i) => {
      const id = c.component_id
      nodes.push({
        id,
        type: "component",
        position: { x: startX + (i % cols) * (LAYOUT.nodeW + LAYOUT.gapX), y: y + Math.floor(i / cols) * (LAYOUT.nodeH + LAYOUT.gapY) },
        data: { component: c, index: globalIdx++, onClick: () => onClick(c), isLoading: loadingId === id, style },
      } as Node<ComponentNodeData, "component">)
    })

    y += Math.ceil(items.length / cols) * (LAYOUT.nodeH + LAYOUT.gapY) + LAYOUT.layerGap
  }

  // Build edges from business_flow (only for visible components)
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

  // Calculate height
  const height = useMemo(() => {
    const { layers, groups } = groupComponents(components)
    return Math.max(500, layers.reduce((h, l) => {
      const n = groups.get(l)?.length || 0
      return n ? h + Math.ceil(n / 3) * 180 + 140 : h
    }, 100))
  }, [components])

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
