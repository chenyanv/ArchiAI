"use client"

import { motion } from "framer-motion"
import { X, FileCode, Copy, Check } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"

interface SourcePanelProps {
  source: {
    source: string
    filePath: string
    startLine: number
    endLine: number
  }
  onClose: () => void
}

export function SourcePanel({ source, onClose }: SourcePanelProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(source.source)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const lines = source.source.split("\n")

  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="fixed right-0 top-14 bottom-0 w-[480px] bg-zinc-900 text-zinc-100 shadow-2xl z-40 flex flex-col"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-700">
        <div className="flex items-center gap-2 min-w-0">
          <FileCode className="w-4 h-4 text-zinc-400 shrink-0" />
          <span className="text-sm font-mono truncate">{source.filePath}</span>
          <span className="text-xs text-zinc-500 shrink-0">
            L{source.startLine}-{source.endLine}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            className="text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
          >
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800"
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Code */}
      <div className="flex-1 overflow-auto">
        <pre className="p-4 text-sm font-mono leading-relaxed">
          <code>
            {lines.map((line, i) => (
              <div key={i} className="flex">
                <span className="w-12 text-right pr-4 text-zinc-600 select-none shrink-0">
                  {source.startLine + i}
                </span>
                <span className="flex-1 whitespace-pre-wrap break-all">{line || " "}</span>
              </div>
            ))}
          </code>
        </pre>
      </div>
    </motion.div>
  )
}
