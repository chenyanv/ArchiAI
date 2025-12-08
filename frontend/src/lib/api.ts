const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

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
