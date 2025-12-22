"use client"

import { motion } from "framer-motion"
import { ChevronRight, FileCode, FolderOpen, Box, Workflow, Database, Globe, Cpu, Loader2 } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { type Component, type DrilldownResponse, type NavigationNode, type NavigationBreadcrumb } from "@/lib/api"

const nodeTypeIcons: Record<string, typeof Box> = {
  file: FileCode,
  directory: FolderOpen,
  module: Box,
  function: Workflow,
  class: Database,
  endpoint: Globe,
  default: Cpu,
}

interface DrilldownViewProps {
  response: DrilldownResponse
  componentCard: Component
  onNodeClick: (node: NavigationNode, componentCard: Component, breadcrumbs: NavigationBreadcrumb[]) => void
  loadingId: string | null
}

export function DrilldownView({ response, componentCard, onNodeClick, loadingId }: DrilldownViewProps) {
  const Icon = nodeTypeIcons[response.nodes[0]?.node_type] || nodeTypeIcons.default

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-6"
    >
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
        <h1 className="text-2xl font-bold">{response.agent_goal}</h1>
        <p className="text-zinc-600 mt-2">{response.rationale}</p>
      </div>

      {/* Nodes */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-zinc-500 uppercase tracking-wider">
          {response.is_sequential ? "Sequence" : "Related Items"}
        </h2>

        <div className={response.is_sequential ? "space-y-2" : "grid grid-cols-1 md:grid-cols-2 gap-3"}>
          {response.nodes.map((node, i) => {
            const NodeIcon = nodeTypeIcons[node.node_type] || nodeTypeIcons.default
            const isLoading = loadingId === node.node_key

            return (
              <motion.div
                key={node.node_key}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.05 }}
              >
                <Card
                  className={`cursor-pointer transition-all hover:shadow-md hover:border-zinc-300 ${
                    isLoading ? "border-zinc-400 bg-zinc-50" : ""
                  }`}
                  onClick={() => onNodeClick(node, componentCard, response.breadcrumbs)}
                >
                  <CardHeader className="pb-2">
                    <div className="flex items-start gap-3">
                      {response.is_sequential && (
                        <div className="flex flex-col items-center">
                          <div className="w-7 h-7 rounded-full bg-zinc-100 flex items-center justify-center text-sm font-medium">
                            {(node.sequence_order ?? i) + 1}
                          </div>
                          {i < response.nodes.length - 1 && (
                            <div className="w-0.5 h-8 bg-zinc-200 mt-1" />
                          )}
                        </div>
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <div className="p-1.5 rounded bg-zinc-100">
                            {isLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <NodeIcon className="w-4 h-4" />
                            )}
                          </div>
                          <CardTitle className="text-base truncate">{node.title}</CardTitle>
                          <Badge variant="outline" className="ml-auto shrink-0">
                            {node.action_kind === "inspect_source" ? "Source" : "Drill"}
                          </Badge>
                        </div>
                        <CardDescription className="mt-1 line-clamp-2">
                          {node.description}
                        </CardDescription>
                      </div>
                      <ChevronRight className="w-5 h-5 text-zinc-400 shrink-0" />
                    </div>
                  </CardHeader>
                </Card>
              </motion.div>
            )
          })}
        </div>
      </div>
    </motion.div>
  )
}
