"use client"

import type { SemanticMetadata } from "@/lib/api"
import { AlertCircle, Zap, Shield, TrendingUp } from "lucide-react"

interface SemanticBadgeProps {
  metadata: SemanticMetadata | undefined
  compact?: boolean
}

// Map semantic roles to colors
const ROLE_COLORS: Record<string, { bg: string; text: string; Icon: typeof AlertCircle }> = {
  gateway: { bg: "bg-blue-50", text: "text-blue-700", Icon: AlertCircle },
  processor: { bg: "bg-purple-50", text: "text-purple-700", Icon: Zap },
  orchestrator: { bg: "bg-amber-50", text: "text-amber-700", Icon: TrendingUp },
  validator: { bg: "bg-green-50", text: "text-green-700", Icon: Shield },
  transformer: { bg: "bg-indigo-50", text: "text-indigo-700", Icon: Zap },
  adapter: { bg: "bg-cyan-50", text: "text-cyan-700", Icon: AlertCircle },
  mediator: { bg: "bg-rose-50", text: "text-rose-700", Icon: AlertCircle },
  sink: { bg: "bg-slate-50", text: "text-slate-700", Icon: AlertCircle },
  repository: { bg: "bg-lime-50", text: "text-lime-700", Icon: Shield },
  factory: { bg: "bg-orange-50", text: "text-orange-700", Icon: Zap },
  strategy: { bg: "bg-fuchsia-50", text: "text-fuchsia-700", Icon: AlertCircle },
  aggregator: { bg: "bg-teal-50", text: "text-teal-700", Icon: TrendingUp },
  dispatcher: { bg: "bg-pink-50", text: "text-pink-700", Icon: Zap },
}

// Map risk levels to colors
const RISK_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-300",
  high: "bg-orange-100 text-orange-800 border-orange-300",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-300",
  low: "bg-green-100 text-green-800 border-green-300",
}

/**
 * SemanticBadge: Compact display of semantic role and risk level
 *
 * Shows the semantic role (e.g., "Gateway") with color-coded styling
 * and risk level indicator when applicable.
 */
export function SemanticBadge({ metadata, compact = false }: SemanticBadgeProps) {
  if (!metadata?.semantic_role) return null

  const roleConfig = ROLE_COLORS[metadata.semantic_role] || ROLE_COLORS.gateway
  const { bg, text, Icon } = roleConfig
  const riskClass = metadata.risk_level ? RISK_COLORS[metadata.risk_level.toLowerCase()] : null

  if (compact) {
    return (
      <div className="flex items-center gap-1">
        <div className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-semibold ${bg} ${text}`}>
          <Icon className="w-3 h-3" />
          <span>{metadata.semantic_role}</span>
        </div>
        {riskClass && (
          <div className={`inline-flex px-2 py-1 rounded-full text-xs font-semibold border ${riskClass}`}>
            {metadata.risk_level?.toUpperCase()}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className={`inline-flex items-center gap-2 px-3 py-2 rounded-lg ${bg} ${text}`}>
        <Icon className="w-4 h-4" />
        <span className="font-semibold capitalize">{metadata.semantic_role}</span>
      </div>
      {riskClass && (
        <div className={`inline-flex ml-2 px-3 py-2 rounded-lg text-sm font-semibold border ${riskClass}`}>
          Risk: {metadata.risk_level?.toUpperCase()}
        </div>
      )}
    </div>
  )
}

export default SemanticBadge
