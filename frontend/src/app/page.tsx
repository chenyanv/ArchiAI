import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Network, Waypoints, Bot, ArrowRight } from "lucide-react"
import { GraphBackground } from "@/components/graph-background"
import { RepoSearch } from "@/components/repo-search"
import Link from "next/link"

export default function Page() {
  return (
    <div className="min-h-screen bg-white">
      {/* Header */}
      <header className="absolute top-0 left-0 right-0 z-20 px-6 py-4">
        <div className="mx-auto max-w-7xl flex items-center justify-between">
          <Link href="/" className="text-xl font-bold text-black tracking-tight">
            Arch AI
          </Link>
          <nav className="flex items-center gap-6">
            <Link href="/pricing" className="text-sm text-zinc-600 hover:text-black transition-colors">
              Pricing
            </Link>
            <Link href="/login" className="text-sm text-zinc-600 hover:text-black transition-colors">
              Log in
            </Link>
            <Button asChild className="bg-black hover:bg-zinc-800 text-white">
              <Link href="/signup">Sign up</Link>
            </Button>
          </nav>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative min-h-screen flex items-center px-6 overflow-hidden">
        <GraphBackground />

        <div className="relative z-10 mx-auto max-w-4xl w-full pt-20">
          <h1 className="mb-6 text-4xl font-bold tracking-tight text-black md:text-5xl lg:text-6xl text-left">
            <span className="whitespace-nowrap">Stop Reading Code.</span>
            <br />
            <span className="whitespace-nowrap">Start Understanding Systems.</span>
          </h1>

          <p className="mb-4 text-2xl text-zinc-600 md:text-3xl text-balance">
            The Living Blueprint for Open Source.
          </p>

          <p className="mb-12 text-lg text-zinc-500 md:text-xl">
            From git clone to &apos;I get it&apos; in seconds.
          </p>

          <RepoSearch />
        </div>
      </section>

      {/* Feature Grid */}
      <section className="px-6 py-20 bg-zinc-50/50">
        <div className="mx-auto max-w-6xl">
          <div className="grid gap-6 md:grid-cols-3">
            {/* Card 1 - Architecture Topology */}
            <Card className="border-zinc-200 bg-white hover:shadow-lg transition-shadow">
              <CardHeader>
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-black">
                  <Network className="h-6 w-6 text-white" />
                </div>
                <CardTitle className="text-xl text-black">Architecture Topology</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base text-zinc-600">
                  God-mode view of modules and dependencies. No more getting lost in file trees.
                </CardDescription>
              </CardContent>
            </Card>

            {/* Card 2 - Workflow Tracing */}
            <Card className="border-zinc-200 bg-white hover:shadow-lg transition-shadow">
              <CardHeader>
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-black">
                  <Waypoints className="h-6 w-6 text-white" />
                </div>
                <CardTitle className="text-xl text-black">Workflow Tracing</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base text-zinc-600">
                  Trace the life of a request. See exactly how data flows from API to DB.
                </CardDescription>
              </CardContent>
            </Card>

            {/* Card 3 - AI Code Companion */}
            <Card className="border-zinc-200 bg-white hover:shadow-lg transition-shadow">
              <CardHeader>
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-black">
                  <Bot className="h-6 w-6 text-white" />
                </div>
                <CardTitle className="text-xl text-black">AI Code Companion</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="text-base text-zinc-600">
                  Context-aware explanations based on AST analysis, not just generic LLM chat.
                </CardDescription>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Popular Repos Section */}
      <section className="px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="mb-10 text-center text-3xl font-bold tracking-tight text-black md:text-4xl">
            Explore Analyzed Projects
          </h2>

          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {/* Repo Cards */}
            {[
              {
                name: "RAGFlow",
                description: "Open-source RAG engine based on deep document understanding",
                tags: ["Python", "Docker", "RAG"],
              },
              {
                name: "LangChain",
                description: "Building applications with LLMs through composability",
                tags: ["Python", "TypeScript", "LLM"],
              },
              {
                name: "AutoGPT",
                description: "An experimental open-source autonomous AI agent",
                tags: ["Python", "AI Agent", "GPT"],
              },
              {
                name: "FastAPI",
                description: "Modern, fast web framework for building APIs with Python",
                tags: ["Python", "API", "Framework"],
              },
              {
                name: "Transformers",
                description: "State-of-the-art Machine Learning for PyTorch and TensorFlow",
                tags: ["Python", "ML", "PyTorch"],
              },
              {
                name: "Supabase",
                description: "Open source Firebase alternative with real-time subscriptions",
                tags: ["TypeScript", "PostgreSQL", "Backend"],
              },
            ].map((repo) => (
              <Card
                key={repo.name}
                className="group border-zinc-200 bg-white hover:border-black transition-all cursor-pointer"
              >
                <CardHeader>
                  <div className="flex items-start justify-between mb-2">
                    <CardTitle className="text-lg text-black group-hover:underline">{repo.name}</CardTitle>
                    <ArrowRight className="h-5 w-5 text-zinc-400 group-hover:text-black group-hover:translate-x-1 transition-all" />
                  </div>
                  <CardDescription className="text-sm text-zinc-600">{repo.description}</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-2">
                    {repo.tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="bg-zinc-100 text-zinc-700 border-0">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-200 bg-white px-6 py-12">
        <div className="mx-auto max-w-6xl">
          <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
            <div className="text-center md:text-left">
              <p className="text-sm text-zinc-600">
                © 2025 Arch AI. Built for developers who actually read code.
              </p>
            </div>

            <div className="flex flex-col items-center gap-3 text-sm md:flex-row md:gap-6">
              <a href="mailto:support@archai.dev" className="text-zinc-600 hover:text-black transition-colors">
                support@archai.dev
              </a>
              <span className="hidden md:inline text-zinc-300">•</span>
              <a
                href="https://twitter.com/archai"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-600 hover:text-black transition-colors"
              >
                Twitter
              </a>
              <span className="hidden md:inline text-zinc-300">•</span>
              <a
                href="https://github.com/archai"
                target="_blank"
                rel="noopener noreferrer"
                className="text-zinc-600 hover:text-black transition-colors"
              >
                GitHub
              </a>
            </div>
          </div>

          <div className="mt-6 text-center text-xs text-zinc-400">
            Designed with precision. Built with Next.js.
          </div>
        </div>
      </footer>
    </div>
  )
}
