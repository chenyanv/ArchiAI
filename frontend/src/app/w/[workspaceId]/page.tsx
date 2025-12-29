"use client"

import { useState, useEffect, useCallback } from "react"
import { useParams } from "next/navigation"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowLeft, Boxes, ChevronRight, Loader2 } from "lucide-react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  getStreamUrl,
  drilldownStream,
  getNodeSource,
  type Component,
  type ComponentEdge,
  type RankedGroup,
  type SystemOverview,
  type SSEEvent,
  type DrilldownResponse,
  type NavigationNode,
} from "@/lib/api"
import {
  ArchitectureGraph,
  LoadingView,
  DrilldownGraph,
  SourcePanel,
  SemanticPanel,
  StatCard,
} from "@/components/workspace"

// === Types ===

type HistoryEntry = {
  type: "root"
  rankedGroups: RankedGroup[]
  cacheId?: string
} | {
  type: "drilldown"
  response: DrilldownResponse
  componentCard: Component
  cacheId: string  // Cache ID for this drilldown level
}

type AnalysisState = {
  status: "loading" | "analyzing" | "done" | "error"
  logs: string[]
  overview?: SystemOverview
  rankedGroups?: RankedGroup[]
  businessFlow?: ComponentEdge[]
  error?: string
}

type SourcePanelState = {
  source: string
  filePath: string
  startLine: number
  endLine: number
} | null

type SemanticPanelState = NavigationNode | null

// === Main Page ===

export default function WorkspacePage() {
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const [state, setState] = useState<AnalysisState>({ status: "loading", logs: [] })
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingNodeKey, setLoadingNodeKey] = useState<string | null>(null)
  const [sourcePanel, setSourcePanel] = useState<SourcePanelState>(null)
  const [semanticPanel, setSemanticPanel] = useState<SemanticPanelState>(null)
  const [error, setError] = useState<string | null>(null)
  const [drilldownLogs, setDrilldownLogs] = useState<string[]>([])
  const [drilldownLoading, setDrilldownLoading] = useState(false)

  // SSE connection for analysis
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
        const rankedGroups = data.data?.ranked_components || []
        const businessFlow = data.data?.business_flow || []
        setState((prev) => ({
          ...prev,
          status: "done",
          logs: [...prev.logs, data.message],
          overview: data.data?.system_overview,
          rankedGroups,
          businessFlow,
        }))
        setHistory([{ type: "root", rankedGroups }])
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

  const currentEntry = history[history.length - 1]
  const canGoBack = history.length > 1

  const handleBack = useCallback(() => {
    if (canGoBack) {
      setHistory((prev) => prev.slice(0, -1))
      setSourcePanel(null)
      setSemanticPanel(null)
    }
  }, [canGoBack])

  // Auto-clear errors
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 3000)
      return () => clearTimeout(timer)
    }
  }, [error])

  // Shared drilldown execution
  const executeDrilldown = useCallback(async (component: Component, cacheId?: string, clickedNode?: NavigationNode) => {
    setLoading(true)
    setDrilldownLoading(true)
    setDrilldownLogs([])
    setError(null)

    try {
      await drilldownStream(workspaceId, component, cacheId, (event) => {
        if (event.status === "error") {
          setError(event.message)
          setDrilldownLoading(false)
        } else if (event.status === "done" && event.data) {
          setHistory((prev) => [...prev, { type: "drilldown", response: event.data!, componentCard: component, cacheId: event.data!.cache_id }])
          setDrilldownLoading(false)
        } else if (event.status === "thinking") {
          setDrilldownLogs((prev) => prev.includes(event.message) ? prev : [...prev, event.message])
        }
      }, clickedNode)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to drill down")
      setDrilldownLoading(false)
    } finally {
      setLoading(false)
      setLoadingNodeKey(null)
    }
  }, [workspaceId])

  const handleComponentClick = useCallback(async (component: Component) => {
    setLoadingNodeKey(component.component_id)
    await executeDrilldown(component)
  }, [executeDrilldown])

  const handleSemanticClick = useCallback((node: NavigationNode) => {
    if (node.semantic_metadata) {
      setSemanticPanel(node)
    }
  }, [])

  const handleNodeClick = useCallback(async (
    node: NavigationNode,
    componentCard: Component,
    currentCacheId: string
  ) => {
    setLoadingNodeKey(node.node_key)
    setError(null)

    if (node.action_kind === "inspect_source") {
      if (!node.target_id) {
        // No target_id available - show error instead of silently failing
        setError("Source code location not available for this node")
        setLoadingNodeKey(null)
        return
      }
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
        // Graceful error handling for missing source code
        const errorMsg = e instanceof Error ? e.message : "Failed to load source"
        if (errorMsg.includes("404") || errorMsg.includes("not found")) {
          setError(`Source code not indexed for "${node.title}". This may be a private method or dynamically generated node.`)
        } else {
          setError(errorMsg)
        }
      } finally {
        setLoading(false)
        setLoadingNodeKey(null)
      }
    } else if (node.action_kind === "component_drilldown") {
      // Pass current cache_id and clicked node - backend will load breadcrumbs from cache and append new node
      await executeDrilldown(componentCard, currentCacheId, node)
    } else {
      // Unknown action kind
      setError(`Unknown action: ${node.action_kind}`)
      setLoadingNodeKey(null)
    }
  }, [workspaceId, executeDrilldown])

  const repoName = workspaceId.replace("-", "/")

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
            <button onClick={handleBack} className="flex items-center gap-2 text-sm font-medium hover:underline">
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          ) : (
            <Link href="/" className="flex items-center gap-2 text-sm font-medium hover:underline">
              <ArrowLeft className="w-4 h-4" />
              Home
            </Link>
          )}

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
            <motion.div initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}>
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
                      <motion.div key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} className="text-zinc-500">
                        <span className="text-black mr-2">→</span>
                        {log}
                      </motion.div>
                    ))}
                    {drilldownLogs.length === 0 && <div className="text-zinc-400">Starting analysis...</div>}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex">
        <main className={`flex-1 max-w-6xl mx-auto px-6 py-8 transition-all ${sourcePanel || semanticPanel ? "mr-[480px]" : ""}`}>
          <AnimatePresence mode="wait">
            {state.status !== "done" ? (
              <LoadingView key="loading" repoName={repoName} logs={state.logs} error={state.error} />
            ) : currentEntry?.type === "root" ? (
              <ResultsView
                key="results"
                repoName={repoName}
                overview={state.overview!}
                rankedGroups={currentEntry.rankedGroups}
                businessFlow={state.businessFlow || []}
                onComponentClick={handleComponentClick}
                loadingId={loadingNodeKey}
              />
            ) : currentEntry?.type === "drilldown" ? (
              <DrilldownGraph
                key={`drilldown-${history.length}`}
                response={currentEntry.response}
                componentCard={currentEntry.componentCard}
                onNodeClick={handleNodeClick}
                onSemanticClick={handleSemanticClick}
                loadingId={loadingNodeKey}
              />
            ) : null}
          </AnimatePresence>
        </main>

        <AnimatePresence>
          {sourcePanel && <SourcePanel source={sourcePanel} onClose={() => setSourcePanel(null)} />}
        </AnimatePresence>

        <AnimatePresence>
          {semanticPanel && <SemanticPanel node={semanticPanel} onClose={() => setSemanticPanel(null)} />}
        </AnimatePresence>
      </div>
    </div>
  )
}

// === Page-specific Views ===

function ResultsView({
  repoName,
  overview,
  rankedGroups,
  businessFlow,
  onComponentClick,
  loadingId,
}: {
  repoName: string
  overview: SystemOverview
  rankedGroups: RankedGroup[]
  businessFlow: ComponentEdge[]
  onComponentClick: (component: Component) => void
  loadingId: string | null
}) {
  const totalComponents = rankedGroups.reduce((sum, g) => sum + g.components.length, 0)

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="space-y-8"
    >
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{repoName}</h1>
        <p className="text-zinc-600 mt-2 max-w-3xl leading-relaxed">{overview.headline}</p>
        {overview.key_workflows.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {overview.key_workflows.map((workflow, i) => (
              <Badge key={i} variant="secondary">{workflow}</Badge>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Components" value={totalComponents} icon={Boxes} />
      </div>

      <div>
        <h2 className="text-xl font-semibold mb-4">Architecture</h2>
        <ArchitectureGraph rankedGroups={rankedGroups} businessFlow={businessFlow} onComponentClick={onComponentClick} loadingId={loadingId} />
      </div>
    </motion.div>
  )
}
