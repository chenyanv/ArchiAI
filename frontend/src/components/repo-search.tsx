"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { analyzeRepo } from "@/lib/api"

const EXAMPLES = [
  { label: "RAGFlow", url: "https://github.com/infiniflow/ragflow" },
  { label: "LangChain", url: "https://github.com/langchain-ai/langchain" },
  { label: "AutoGPT", url: "https://github.com/Significant-Gravitas/AutoGPT" },
]

export function RepoSearch() {
  const router = useRouter()
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const handleSubmit = async (githubUrl: string) => {
    if (!githubUrl.trim()) return
    setLoading(true)
    setError("")
    try {
      const { workspace_id } = await analyzeRepo(githubUrl)
      router.push(`/w/${workspace_id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to analyze")
      setLoading(false)
    }
  }

  return (
    <>
      <div className="mx-auto max-w-2xl mb-6">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            handleSubmit(url)
          }}
        >
          <Input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="Paste GitHub Repository URL (e.g., https://github.com/infiniflow/ragflow)"
            className="h-14 flex-1 text-base px-6 border-zinc-300 focus-visible:ring-black"
            disabled={loading}
          />
          <Button
            type="submit"
            disabled={loading}
            className="h-14 px-8 bg-black hover:bg-zinc-800 text-white font-medium"
          >
            {loading ? "Analyzing..." : "Analyze Architecture"}
          </Button>
        </form>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        <span className="text-sm text-zinc-500">Try these:</span>
        {EXAMPLES.map((ex) => (
          <Badge
            key={ex.label}
            variant="outline"
            className="cursor-pointer hover:bg-zinc-100 border-zinc-300 text-zinc-700"
            onClick={() => {
              setUrl(ex.url)
              handleSubmit(ex.url)
            }}
          >
            {ex.label}
          </Badge>
        ))}
      </div>
    </>
  )
}
