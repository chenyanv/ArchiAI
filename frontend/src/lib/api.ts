const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

// Types
export interface SystemOverview {
  headline: string
  key_workflows: string[]
}

export interface Component {
  component_id: string
  module_name: string
  business_signal: string
  confidence: string
  objective: string[]
  leading_landmarks: Array<{ node_id?: string; symbol?: string; summary?: string }>
}

export interface SSEEvent {
  status: "indexing" | "orchestrating" | "done" | "error"
  message: string
  data?: {
    system_overview: SystemOverview
    components: Component[]
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
