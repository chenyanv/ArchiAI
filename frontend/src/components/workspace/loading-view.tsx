"use client"

import { motion } from "framer-motion"
import { Loader2 } from "lucide-react"

interface LoadingViewProps {
  repoName: string
  logs: string[]
  error?: string
}

export function LoadingView({ repoName, logs, error }: LoadingViewProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex flex-col items-center justify-center min-h-[60vh] gap-6"
    >
      <div className="text-center">
        <h1 className="text-2xl font-bold">{repoName}</h1>
        <p className="text-zinc-500 mt-1">Analyzing repository architecture...</p>
      </div>

      {error ? (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg max-w-md">
          {error}
        </div>
      ) : (
        <>
          <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />

          <div className="w-full max-w-md space-y-2">
            {logs.slice(-5).map((log, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="text-sm text-zinc-500 font-mono bg-zinc-100 px-3 py-2 rounded"
              >
                <span className="text-zinc-400 mr-2">→</span>
                {log}
              </motion.div>
            ))}
          </div>
        </>
      )}
    </motion.div>
  )
}
