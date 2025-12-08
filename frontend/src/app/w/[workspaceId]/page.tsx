"use client"

import { useState, useEffect } from "react"
import { useParams } from "next/navigation"
import { motion, AnimatePresence } from "framer-motion"
import { ArrowLeft, GitBranch, Boxes, ChevronRight, Loader2 } from "lucide-react"
import Link from "next/link"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { getStreamUrl, type Component, type SystemOverview, type SSEEvent } from "@/lib/api"

type AnalysisState = {
  status: "loading" | "analyzing" | "done" | "error"
  logs: string[]
  overview?: SystemOverview
  components?: Component[]
  error?: string
}

export default function WorkspacePage() {
  const params = useParams()
  const workspaceId = params.workspaceId as string
  const [state, setState] = useState<AnalysisState>({ status: "loading", logs: [] })

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
        setState((prev) => ({
          ...prev,
          status: "done",
          logs: [...prev.logs, data.message],
          overview: data.data?.system_overview,
          components: data.data?.components,
        }))
        eventSource.close()
        return
      }

      setState((prev) => ({
        ...prev,
        status: "analyzing",
        logs: data.message ? [...prev.logs.filter((l) => l !== data.message), data.message] : prev.logs,
      }))
    }

    eventSource.onerror = () => {
      setState((prev) => ({ ...prev, status: "error", error: "Connection lost" }))
      eventSource.close()
    }

    return () => eventSource.close()
  }, [workspaceId])

  const repoName = workspaceId.replace("-", "/")

  return (
    <div className="min-h-screen bg-zinc-50">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b bg-white/95 backdrop-blur">
        <div className="max-w-6xl mx-auto px-6 flex h-14 items-center">
          <Link href="/" className="flex items-center gap-2 text-sm font-medium hover:underline">
            <ArrowLeft className="w-4 h-4" />
            Back
          </Link>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <AnimatePresence mode="wait">
          {state.status !== "done" ? (
            <LoadingView
              key="loading"
              repoName={repoName}
              logs={state.logs}
              error={state.error}
            />
          ) : (
            <ResultsView
              key="results"
              repoName={repoName}
              overview={state.overview!}
              components={state.components!}
            />
          )}
        </AnimatePresence>
      </main>
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
}: {
  repoName: string
  overview: SystemOverview
  components: Component[]
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-8"
    >
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">{repoName}</h1>
        <p className="text-zinc-600 mt-2 max-w-3xl leading-relaxed">
          {overview.headline}
        </p>

        {overview.key_workflows.length > 0 && (
          <div className="flex flex-wrap gap-2 mt-4">
            {overview.key_workflows.map((workflow, i) => (
              <Badge key={i} variant="secondary">
                {workflow}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Components" value={components.length} icon={Boxes} />
      </div>

      {/* Components */}
      <div>
        <h2 className="text-xl font-semibold mb-4">Components</h2>
        <div className="grid md:grid-cols-2 gap-4">
          {components.map((component) => (
            <ComponentCard key={component.component_id} component={component} />
          ))}
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

function ComponentCard({ component }: { component: Component }) {
  const confidence = component.confidence === "high" ? 90 : component.confidence === "medium" ? 70 : 50

  return (
    <Card className="hover:border-black/30 transition-colors cursor-pointer group">
      <CardHeader>
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <CardTitle className="text-base group-hover:underline">
              {component.module_name}
            </CardTitle>
            <CardDescription className="font-mono text-xs mt-1">
              {component.component_id}
            </CardDescription>
          </div>
          <Badge variant="outline" className="font-mono text-xs">
            {component.confidence}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-sm text-zinc-600">{component.business_signal}</p>

        {component.objective.length > 0 && (
          <ul className="space-y-1">
            {component.objective.slice(0, 2).map((q, i) => (
              <li key={i} className="text-xs text-zinc-500 flex items-start gap-1">
                <ChevronRight className="w-3 h-3 mt-0.5 shrink-0" />
                <span className="line-clamp-1">{q}</span>
              </li>
            ))}
          </ul>
        )}

        <Progress value={confidence} className="h-1.5" />
      </CardContent>
    </Card>
  )
}
