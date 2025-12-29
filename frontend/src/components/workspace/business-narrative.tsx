"use client"

import type { SemanticMetadata } from "@/lib/api"
import { BookOpen, AlertCircle, Workflow, Network } from "lucide-react"

interface BusinessNarrativeProps {
  narrative?: string
  metadata?: SemanticMetadata
  title: string
}

/**
 * BusinessNarrative: Story-format explanation of a component's role
 *
 * Displays:
 * - Business narrative (story-format explanation)
 * - Business context (what it does in business terms)
 * - Significance (why it matters)
 * - Impacted workflows (what depends on it)
 */
export function BusinessNarrative({ narrative, metadata, title }: BusinessNarrativeProps) {
  if (!narrative && !metadata?.business_context && !metadata?.impacted_workflows?.length) {
    return null
  }

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <BookOpen className="w-5 h-5 text-blue-600" />
        <h3 className="font-semibold text-slate-900">Business Context: {title}</h3>
      </div>

      {/* Main narrative */}
      {narrative && (
        <div className="space-y-2">
          <p className="text-sm text-slate-700 leading-relaxed italic">{narrative}</p>
        </div>
      )}

      {/* Business context */}
      {metadata?.business_context && (
        <div className="space-y-2 rounded bg-white p-3 border border-slate-200">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-amber-600" />
            <span className="text-xs font-semibold text-slate-600 uppercase">What It Does</span>
          </div>
          <p className="text-sm text-slate-700">{metadata.business_context}</p>
        </div>
      )}

      {/* Business significance */}
      {metadata?.business_significance && (
        <div className="space-y-2 rounded bg-white p-3 border border-slate-200">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-600" />
            <span className="text-xs font-semibold text-slate-600 uppercase">Why It Matters</span>
          </div>
          <p className="text-sm text-slate-700">{metadata.business_significance}</p>
        </div>
      )}

      {/* Impacted workflows */}
      {metadata?.impacted_workflows && metadata.impacted_workflows.length > 0 && (
        <div className="space-y-2 rounded bg-white p-3 border border-slate-200">
          <div className="flex items-center gap-2">
            <Workflow className="w-4 h-4 text-green-600" />
            <span className="text-xs font-semibold text-slate-600 uppercase">Impacted Workflows</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {metadata.impacted_workflows.map((workflow) => (
              <span
                key={workflow}
                className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-50 text-green-700 border border-green-200"
              >
                {workflow}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Dependencies */}
      {metadata?.dependencies_description && (
        <div className="space-y-2 rounded bg-white p-3 border border-slate-200">
          <div className="flex items-center gap-2">
            <Network className="w-4 h-4 text-purple-600" />
            <span className="text-xs font-semibold text-slate-600 uppercase">Dependencies</span>
          </div>
          <p className="text-sm text-slate-700">{metadata.dependencies_description}</p>
        </div>
      )}
    </div>
  )
}

export default BusinessNarrative
