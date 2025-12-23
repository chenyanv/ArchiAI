const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Types
export interface SystemOverview {
  headline: string
  key_workflows: string[]
}

export interface Component {
  component_id: string
  module_name: string
  directory?: string
  business_signal: string
  architecture_layer: string  // Dynamic - LLM decides categories based on project type
  rank: number  // Layout rank computed from business_flow (0 = entry, higher = downstream)
  confidence: string
  objective: string[]
  leading_landmarks: Array<{ node_id?: string; symbol?: string; summary?: string }>
}

export interface ComponentEdge {
  from_component: string
  to_component: string
  label?: string
}

// Pre-grouped components by rank (computed by backend)
export interface RankedGroup {
  rank: number
  label: string  // "Entry", "Layer 1", "Layer 2", ..., "Data"
  components: Component[]
}

export interface SSEEvent {
  status: "indexing" | "orchestrating" | "done" | "error"
  message: string
  data?: {
    system_overview: SystemOverview
    ranked_components: RankedGroup[]
    business_flow?: ComponentEdge[]
  }
}

// API functions
export async function analyzeRepo(githubUrl: string): Promise<{ workspace_id: string }> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ github_url: githubUrl }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Unknown error" }))
    throw new Error(error.detail || "Failed to analyze")
  }
  return res.json()
}

export function getStreamUrl(workspaceId: string): string {
  return `${API_BASE}/api/workspaces/${workspaceId}/stream`
}

export async function getOverview(workspaceId: string) {
  const res = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/overview`)
  if (!res.ok) {
    throw new Error("Failed to get overview")
  }
  return res.json()
}

// Navigation types
export interface NavigationBreadcrumb {
  node_key: string
  label: string
}

export interface NavigationNode {
  node_key: string
  title: string
  node_type: string
  description: string
  action_kind: "inspect_source" | "component_drilldown"
  target_id?: string
  sequence_order?: number
}

export interface DrilldownResponse {
  component_id: string
  agent_goal: string
  focus_label: string
  rationale: string
  is_sequential: boolean
  nodes: NavigationNode[]
  breadcrumbs: NavigationBreadcrumb[]
}

export interface DrilldownSSEEvent {
  status: "thinking" | "done" | "error"
  message: string
  data?: DrilldownResponse
}

export function getDrilldownStreamUrl(workspaceId: string): string {
  return `${API_BASE}/api/workspaces/${workspaceId}/drilldown/stream`
}

export async function drilldown(
  workspaceId: string,
  componentCard: Component,
  breadcrumbs: NavigationBreadcrumb[] = []
): Promise<DrilldownResponse> {
  const res = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/drilldown`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      component_card: componentCard,
      breadcrumbs,
    }),
  })
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Drilldown failed" }))
    throw new Error(error.detail || "Drilldown failed")
  }
  return res.json()
}

export async function drilldownStream(
  workspaceId: string,
  componentCard: Component,
  breadcrumbs: NavigationBreadcrumb[] = [],
  onMessage: (event: DrilldownSSEEvent) => void
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/drilldown/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      component_card: componentCard,
      breadcrumbs,
    }),
  })

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Drilldown failed" }))
    throw new Error(error.detail || "Drilldown failed")
  }

  const reader = res.body?.getReader()
  if (!reader) throw new Error("No response body")

  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split("\n")
    buffer = lines.pop() || ""

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          const data = JSON.parse(line.slice(6))
          onMessage(data)
        } catch {
          // ignore parse errors
        }
      }
    }
  }
}

export async function getNodeSource(
  nodeId: string,
  workspaceId: string
): Promise<{ source: string; file_path: string; start_line: number; end_line: number }> {
  const res = await fetch(
    `${API_BASE}/api/nodes/${encodeURIComponent(nodeId)}/source?workspace_id=${workspaceId}`
  )
  if (!res.ok) {
    throw new Error("Failed to get source")
  }
  const data = await res.json()
  // Backend returns 'code', map to 'source' for consistency
  return {
    source: data.code,
    file_path: data.file_path,
    start_line: data.start_line,
    end_line: data.end_line,
  }
}
