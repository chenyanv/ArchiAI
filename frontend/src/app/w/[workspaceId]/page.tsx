"use client"

import { useState, useEffect, useCallback } from "react"
import { useParams } from "next/navigation"
import { motion, AnimatePresence } from "framer-motion"
import {
  ArrowLeft,
  Boxes,
  ChevronRight,
  Loader2,
  FileCode,
  Code,
  Box,
  Waypoints,
  Bot,
  Wrench,
  X,
} from "lucide-react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { Button } from "@/components/ui/button"
import {
  getStreamUrl,
  drilldownStream,
  getNodeSource,
  type Component,
  type SystemOverview,
  type SSEEvent,
  type DrilldownResponse,
  type NavigationNode,
  type NavigationBreadcrumb,
} from "@/lib/api"

// Navigation history entry
type HistoryEntry = {
  type: "root"
  components: Component[]
} | {
  type: "drilldown"
  response: DrilldownResponse
  componentCard: Component
}

type AnalysisState = {
  status: "loading" | "analyzing" | "done" | "error"
  logs: string[]
  overview?: SystemOverview
  components?: Component[]
  error?: string
}

type SourcePanelState = {
  source: string
  filePath: string
  startLine: number
  endLine: number
} | null

export default function WorkspacePage() {
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const [state, setState] = useState<AnalysisState>({ status: "loading", logs: [] })
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingNodeKey, setLoadingNodeKey] = useState<string | null>(null)
  const [sourcePanel, setSourcePanel] = useState<SourcePanelState>(null)
  const [error, setError] = useState<string | null>(null)
  const [drilldownLogs, setDrilldownLogs] = useState<string[]>([])
  const [drilldownLoading, setDrilldownLoading] = useState(false)

  // SSE connection
  useEffect(() => {
    const eventSource = new EventSource(getStreamUrl(workspaceId))

    eventSource.onmessage = (event) => {
      const data: SSEEvent = JSON.parse(event.data)

      if (data.status === "error") {
        setState((prev) => ({ ...prev, status: "error", error: data.message }))
        eventSource.close()
        return
      }

      if (data.status === "done") {
        const components = data.data?.components || []
        setState((prev) => ({
          ...prev,
          status: "done",
          logs: [...prev.logs, data.message],
          overview: data.data?.system_overview,
          components,
        }))
        // Initialize history with root
        setHistory([{ type: "root", components }])
        eventSource.close()
        return
      }

      setState((prev) => {
        const newLogs = data.message
          ? [...prev.logs.filter((l) => l !== data.message), data.message]
          : prev.logs
        return {
          ...prev,
          status: "analyzing",
          logs: newLogs,
        }
      })
    }

    eventSource.onerror = () => {
      setState((prev) => ({ ...prev, status: "error", error: "Connection lost" }))
      eventSource.close()
    }

    return () => eventSource.close()
  }, [workspaceId])

  // Current view from history
  const currentEntry = history[history.length - 1]
  const canGoBack = history.length > 1

  // Back navigation
  const handleBack = useCallback(() => {
    if (canGoBack) {
      setHistory((prev) => prev.slice(0, -1))
      setSourcePanel(null)
    }
  }, [canGoBack])

  // Clear error after 3 seconds
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 3000)
      return () => clearTimeout(timer)
    }
  }, [error])

  // Component click -> drilldown with streaming
  const handleComponentClick = useCallback(async (component: Component) => {
    setLoading(true)
    setLoadingNodeKey(component.component_id)
    setDrilldownLoading(true)
    setDrilldownLogs([])
    setError(null)

    try {
      await drilldownStream(workspaceId, component, [], (event) => {
        if (event.status === "error") {
          setError(event.message)
          setDrilldownLoading(false)
        } else if (event.status === "done" && event.data) {
          setHistory((prev) => [...prev, { type: "drilldown", response: event.data!, componentCard: component }])
          setDrilldownLoading(false)
        } else if (event.status === "thinking") {
          setDrilldownLogs((prev) =>
            prev.includes(event.message) ? prev : [...prev, event.message]
          )
        }
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to drill down")
      setDrilldownLoading(false)
    } finally {
      setLoading(false)
      setLoadingNodeKey(null)
    }
  }, [workspaceId])

  // Node click handler
  const handleNodeClick = useCallback(async (node: NavigationNode, componentCard: Component, breadcrumbs: NavigationBreadcrumb[]) => {
    setLoadingNodeKey(node.node_key)
    setError(null)

    if (node.action_kind === "inspect_source" && node.target_id) {
      setLoading(true)
      try {
        const result = await getNodeSource(node.target_id, workspaceId)
        setSourcePanel({
          source: result.source,
          filePath: result.file_path,
          startLine: result.start_line,
          endLine: result.end_line,
        })
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load source")
      } finally {
        setLoading(false)
        setLoadingNodeKey(null)
      }
    } else if (node.action_kind === "component_drilldown") {
      setLoading(true)
      setDrilldownLoading(true)
      setDrilldownLogs([])

      try {
        const newBreadcrumbs = [...breadcrumbs, { node_key: node.node_key, label: node.title }]
        await drilldownStream(workspaceId, componentCard, newBreadcrumbs, (event) => {
          if (event.status === "error") {
            setError(event.message)
            setDrilldownLoading(false)
          } else if (event.status === "done" && event.data) {
            setHistory((prev) => [...prev, { type: "drilldown", response: event.data!, componentCard }])
            setDrilldownLoading(false)
          } else if (event.status === "thinking") {
            setDrilldownLogs((prev) =>
              prev.includes(event.message) ? prev : [...prev, event.message]
            )
          }
        })
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to drill down")
        setDrilldownLoading(false)
      } finally {
        setLoading(false)
        setLoadingNodeKey(null)
      }
    }
  }, [workspaceId])

  const repoName = workspaceId.replace("-", "/")

  // Build breadcrumbs for display
  const breadcrumbs = history.slice(1).map((entry) => {
    if (entry.type === "drilldown") {
      return entry.response.focus_label || entry.componentCard.module_name
    }
    return ""
  }).filter(Boolean)

  return (
    <div className="min-h-screen bg-zinc-50">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b bg-white/95 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 flex h-14 items-center gap-4">
          {canGoBack ? (
            <button
              onClick={handleBack}
              className="flex items-center gap-2 text-sm font-medium hover:underline"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          ) : (
            <Link href="/" className="flex items-center gap-2 text-sm font-medium hover:underline">
              <ArrowLeft className="w-4 h-4" />
              Home
            </Link>
          )}

          {/* Breadcrumbs */}
          {breadcrumbs.length > 0 && (
            <div className="flex items-center gap-1 text-sm text-zinc-500">
              <span className="text-zinc-300">/</span>
              {breadcrumbs.map((crumb, i) => (
                <span key={i} className="flex items-center gap-1">
                  <span className="text-zinc-700">{crumb}</span>
                  {i < breadcrumbs.length - 1 && <ChevronRight className="w-3 h-3" />}
                </span>
              ))}
            </div>
          )}

          {loading && <Loader2 className="w-4 h-4 animate-spin ml-auto" />}
        </div>
      </header>

      {/* Error toast */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="fixed top-20 left-1/2 -translate-x-1/2 z-50 bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded-lg shadow-lg"
          >
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Drilldown loading overlay */}
      <AnimatePresence>
        {drilldownLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/20 backdrop-blur-sm flex items-center justify-center"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
            >
              <Card className="w-96 shadow-xl">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Analyzing...
                  </CardTitle>
                  <CardDescription>Exploring component structure</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2 font-mono text-sm max-h-48 overflow-auto">
                    {drilldownLogs.map((log, i) => (
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        className="text-zinc-500"
                      >
                        <span className="text-black mr-2">→</span>
                        {log}
                      </motion.div>
                    ))}
                    {drilldownLogs.length === 0 && (
                      <div className="text-zinc-400">Starting analysis...</div>
                    )}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex">
        {/* Main content */}
        <main className={`flex-1 max-w-6xl mx-auto px-6 py-8 transition-all ${sourcePanel ? "mr-[480px]" : ""}`}>
          <AnimatePresence mode="wait">
            {state.status !== "done" ? (
              <LoadingView
                key="loading"
                repoName={repoName}
                logs={state.logs}
                error={state.error}
              />
            ) : currentEntry?.type === "root" ? (
              <ResultsView
                key="results"
                repoName={repoName}
                overview={state.overview!}
                components={currentEntry.components}
                onComponentClick={handleComponentClick}
                loadingId={loadingNodeKey}
              />
            ) : currentEntry?.type === "drilldown" ? (
              <DrilldownView
                key={`drilldown-${history.length}`}
                response={currentEntry.response}
                componentCard={currentEntry.componentCard}
                onNodeClick={handleNodeClick}
                loadingId={loadingNodeKey}
              />
            ) : null}
          </AnimatePresence>
        </main>

        {/* Source panel */}
        <AnimatePresence>
          {sourcePanel && (
            <SourcePanel
              source={sourcePanel}
              onClose={() => setSourcePanel(null)}
            />
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function LoadingView({
  repoName,
  logs,
  error,
}: {
  repoName: string
  logs: string[]
  error?: string
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="max-w-xl mx-auto mt-20"
    >
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {error ? (
              <span className="text-red-600">Error</span>
            ) : (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Analyzing {repoName}
              </>
            )}
          </CardTitle>
          <CardDescription>
            {error || "Reading codebase structure..."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2 font-mono text-sm">
            {logs.map((log, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-zinc-500"
              >
                <span className="text-black mr-2">→</span>
                {log}
              </motion.div>
            ))}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  )
}

function ResultsView({
  repoName,
  overview,
  components,
  onComponentClick,
  loadingId,
}: {
  repoName: string
  overview: SystemOverview
  components: Component[]
  onComponentClick: (component: Component) => void
  loadingId: string | null
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-8"
    >
      {/* Header */}
      <div className="border-b border-zinc-200 pb-6">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <code className="text-sm font-mono text-zinc-500">{repoName}</code>
            <h1 className="text-3xl font-bold tracking-tight mt-1">Architecture Overview</h1>
          </div>
          <Badge variant="outline" className="font-mono text-xs">
            {components.length} {components.length === 1 ? "component" : "components"}
          </Badge>
        </div>

        <p className="text-base text-zinc-600 max-w-3xl leading-relaxed">
          {overview.headline}
        </p>

        {overview.key_workflows.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {overview.key_workflows.map((workflow, i) => (
              <Badge key={i} variant="secondary" className="bg-zinc-100 text-zinc-700 border-0 font-normal">
                {workflow}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Components */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-zinc-900">Core Components</h2>
          <span className="text-xs text-zinc-400">Click to explore internals</span>
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          {components.map((component) => (
            <ComponentCard
              key={component.component_id}
              component={component}
              onClick={() => onComponentClick(component)}
              isLoading={loadingId === component.component_id}
            />
          ))}
        </div>
      </div>
    </motion.div>
  )
}

function DrilldownView({
  response,
  componentCard,
  onNodeClick,
  loadingId,
}: {
  response: DrilldownResponse
  componentCard: Component
  onNodeClick: (node: NavigationNode, componentCard: Component, breadcrumbs: NavigationBreadcrumb[]) => void
  loadingId: string | null
}) {
  const { focus_label, rationale, is_sequential, nodes, breadcrumbs } = response

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">{focus_label}</h1>
        <p className="text-zinc-600 mt-2">{rationale}</p>
      </div>

      {/* Nodes */}
      {is_sequential ? (
        <FlowView nodes={nodes} onNodeClick={(node) => onNodeClick(node, componentCard, breadcrumbs)} loadingId={loadingId} />
      ) : (
        <GridView nodes={nodes} onNodeClick={(node) => onNodeClick(node, componentCard, breadcrumbs)} loadingId={loadingId} />
      )}
    </motion.div>
  )
}

function FlowView({
  nodes,
  onNodeClick,
  loadingId,
}: {
  nodes: NavigationNode[]
  onNodeClick: (node: NavigationNode) => void
  loadingId: string | null
}) {
  const sortedNodes = [...nodes].sort((a, b) => (a.sequence_order || 0) - (b.sequence_order || 0))

  return (
    <div className="space-y-3">
      {sortedNodes.map((node, i) => (
        <div key={node.node_key} className="flex items-stretch gap-4">
          {/* Step indicator */}
          <div className="flex flex-col items-center">
            <div className="w-8 h-8 rounded-full bg-black text-white flex items-center justify-center text-sm font-medium">
              {i + 1}
            </div>
            {i < sortedNodes.length - 1 && (
              <div className="w-0.5 flex-1 bg-zinc-200 my-1" />
            )}
          </div>

          {/* Node card */}
          <NodeCard node={node} onClick={() => onNodeClick(node)} className="flex-1" isLoading={loadingId === node.node_key} />
        </div>
      ))}
    </div>
  )
}

function GridView({
  nodes,
  onNodeClick,
  loadingId,
}: {
  nodes: NavigationNode[]
  onNodeClick: (node: NavigationNode) => void
  loadingId: string | null
}) {
  return (
    <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
      {nodes.map((node) => (
        <NodeCard key={node.node_key} node={node} onClick={() => onNodeClick(node)} isLoading={loadingId === node.node_key} />
      ))}
    </div>
  )
}

const nodeTypeIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  tool: Wrench,
  file: FileCode,
  function: Code,
  class: Box,
  workflow: Waypoints,
  agent: Bot,
}

function NodeCard({
  node,
  onClick,
  className = "",
  isLoading = false,
}: {
  node: NavigationNode
  onClick: () => void
  className?: string
  isLoading?: boolean
}) {
  const Icon = nodeTypeIcons[node.node_type] || Code

  return (
    <Card
      className={`cursor-pointer hover:border-black/30 transition-colors group ${isLoading ? "opacity-70 pointer-events-none" : ""} ${className}`}
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start gap-3">
          <div className="p-2 rounded-lg bg-zinc-100 group-hover:bg-zinc-200 transition-colors">
            {isLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Icon className="w-4 h-4" />}
          </div>
          <div className="flex-1 min-w-0">
            <CardTitle className="text-sm group-hover:underline truncate">
              {node.title}
            </CardTitle>
            <Badge variant="outline" className="mt-1 text-xs font-mono">
              {node.node_type}
            </Badge>
          </div>
          {node.action_kind === "component_drilldown" && (
            <ChevronRight className="w-4 h-4 text-zinc-400 group-hover:text-black transition-colors" />
          )}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-zinc-600 line-clamp-2">{node.description}</p>
      </CardContent>
    </Card>
  )
}

function SourcePanel({
  source,
  onClose,
}: {
  source: { source: string; filePath: string; startLine: number; endLine: number }
  onClose: () => void
}) {
  const lines = source.source.split("\n")

  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="fixed right-0 top-14 bottom-0 w-[480px] bg-zinc-900 border-l border-zinc-700 shadow-xl z-40 flex flex-col"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700 bg-zinc-800">
        <div className="min-w-0">
          <h3 className="font-medium text-sm truncate text-zinc-100">{source.filePath}</h3>
          <p className="text-xs text-zinc-400">
            Lines {source.startLine}-{source.endLine}
          </p>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} className="text-zinc-400 hover:text-zinc-100 hover:bg-zinc-700">
          <X className="w-4 h-4" />
        </Button>
      </div>

      {/* Code with line numbers */}
      <div className="flex-1 overflow-auto">
        <div className="flex text-sm font-mono">
          {/* Line numbers */}
          <div className="flex-shrink-0 py-4 pl-4 pr-3 text-right text-zinc-500 select-none border-r border-zinc-700 bg-zinc-800/50">
            {lines.map((_, i) => (
              <div key={i} className="leading-relaxed">
                {source.startLine + i}
              </div>
            ))}
          </div>
          {/* Code */}
          <pre className="flex-1 p-4 overflow-x-auto">
            <code className="text-zinc-100">
              {lines.map((line, i) => (
                <div key={i} className="leading-relaxed hover:bg-zinc-800/50">
                  {line || " "}
                </div>
              ))}
            </code>
          </pre>
        </div>
      </div>
    </motion.div>
  )
}

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: number | string
  icon: React.ComponentType<{ className?: string }>
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center gap-2 text-zinc-500 mb-1">
          <Icon className="w-4 h-4" />
          <span className="text-sm">{label}</span>
        </div>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  )
}

function ComponentCard({
  component,
  onClick,
  isLoading = false,
}: {
  component: Component
  onClick: () => void
  isLoading?: boolean
}) {
  const confidence = component.confidence === "high" ? 90 : component.confidence === "medium" ? 70 : 50

  return (
    <Card
      className={`hover:border-zinc-400 hover:shadow-sm transition-all cursor-pointer group ${isLoading ? "opacity-70 pointer-events-none" : ""}`}
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <code className="text-xs font-mono text-zinc-400 truncate">{component.component_id}</code>
            </div>
            <CardTitle className="text-base font-semibold group-hover:text-black">
              {component.module_name}
            </CardTitle>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin text-zinc-400" />
            ) : (
              <ChevronRight className="w-4 h-4 text-zinc-300 group-hover:text-black transition-colors" />
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <p className="text-sm text-zinc-600 leading-relaxed">{component.business_signal}</p>

        {component.objective.length > 0 && (
          <ul className="space-y-1.5 border-l-2 border-zinc-200 pl-3">
            {component.objective.slice(0, 2).map((q, i) => (
              <li key={i} className="text-xs text-zinc-500 leading-relaxed line-clamp-1">
                {q}
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center gap-2 pt-1">
          <Progress value={confidence} className="h-1 flex-1" />
          <span className="text-xs font-mono text-zinc-400">{confidence}%</span>
        </div>
      </CardContent>
    </Card>
  )
}
