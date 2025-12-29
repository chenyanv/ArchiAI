"use client"

import type { NavigationNode } from "@/lib/api"
import { SemanticBadge } from "./semantic-badge"
import { motion } from "framer-motion"
import { X, AlertTriangle, Info } from "lucide-react"

interface SemanticPanelProps {
  node: NavigationNode
  onClose: () => void
}

/**
 * SemanticPanel: Comprehensive sidebar for displaying semantic metadata
 *
 * Shows all business semantic information for a selected node:
 * - Semantic role with visual indicator
 * - Business narrative and context
 * - Risk assessment
 * - Impacted workflows
 * - Dependencies
 */
export function SemanticPanel({ node, onClose }: SemanticPanelProps) {
  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="fixed right-0 top-14 bottom-0 w-96 bg-white shadow-2xl overflow-y-auto z-40 border-l border-slate-200"
    >
      {/* Header */}
      <div className="sticky top-0 bg-white border-b border-slate-200 p-4 flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h2 className="font-bold text-lg text-slate-900 truncate">{node.title}</h2>
          <p className="text-xs text-slate-500 mt-1">{node.node_type}</p>
        </div>
        <button
          onClick={onClose}
          className="flex-shrink-0 p-2 hover:bg-slate-100 rounded-lg transition-colors"
        >
          <X className="w-5 h-5 text-slate-500" />
        </button>
      </div>

      {/* Content */}
      <div className="p-4 space-y-6">
              {/* Node Description */}
              <div className="space-y-2">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Description</h3>
                <p className="text-sm text-slate-700 leading-relaxed">{node.description}</p>
              </div>

              {/* Semantic Role & Risk */}
              {node.semantic_metadata && (
                <>
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Semantic Information</h3>
                    <div className="pt-2">
                      <SemanticBadge metadata={node.semantic_metadata} compact={false} />
                    </div>
                  </div>

                  {/* Business Narrative */}
                  {(node.business_narrative ||
                    node.semantic_metadata.business_context ||
                    node.semantic_metadata.impacted_workflows) && (
                    <div className="space-y-2">
                      <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Business Context</h3>
                      <div className="space-y-3 pt-2">
                        {node.business_narrative && (
                          <div className="text-sm italic text-slate-700 bg-blue-50 p-3 rounded-lg border border-blue-200">
                            {node.business_narrative}
                          </div>
                        )}

                        {node.semantic_metadata.business_context && (
                          <div className="space-y-1">
                            <label className="text-xs font-semibold text-slate-600">What It Does</label>
                            <p className="text-sm text-slate-700">{node.semantic_metadata.business_context}</p>
                          </div>
                        )}

                        {node.semantic_metadata.business_significance && (
                          <div className="space-y-1">
                            <label className="flex items-center gap-1 text-xs font-semibold text-slate-600">
                              <AlertTriangle className="w-3 h-3 text-amber-600" />
                              Why It Matters
                            </label>
                            <p className="text-sm text-slate-700">{node.semantic_metadata.business_significance}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* Risk & Flow Position */}
                  {(node.semantic_metadata.risk_level || node.semantic_metadata.flow_position) && (
                    <div className="grid grid-cols-2 gap-3">
                      {node.semantic_metadata.risk_level && (
                        <div className="space-y-1">
                          <label className="text-xs font-semibold text-slate-600">Risk Level</label>
                          <div
                            className={`px-2 py-1 rounded text-xs font-semibold text-center ${
                              {
                                critical: "bg-red-100 text-red-800",
                                high: "bg-orange-100 text-orange-800",
                                medium: "bg-yellow-100 text-yellow-800",
                                low: "bg-green-100 text-green-800",
                              }[node.semantic_metadata.risk_level.toLowerCase()] || "bg-slate-100 text-slate-800"
                            }`}
                          >
                            {node.semantic_metadata.risk_level}
                          </div>
                        </div>
                      )}

                      {node.semantic_metadata.flow_position && (
                        <div className="space-y-1">
                          <label className="text-xs font-semibold text-slate-600">Flow Position</label>
                          <div className="px-2 py-1 rounded text-xs font-semibold text-center bg-indigo-100 text-indigo-800">
                            {node.semantic_metadata.flow_position}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Impacted Workflows */}
                  {node.semantic_metadata.impacted_workflows &&
                    node.semantic_metadata.impacted_workflows.length > 0 && (
                      <div className="space-y-2">
                        <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                          Impacted Workflows
                        </label>
                        <div className="space-y-2">
                          {node.semantic_metadata.impacted_workflows.map((workflow) => (
                            <div
                              key={workflow}
                              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200"
                            >
                              <Info className="w-4 h-4 text-green-600 flex-shrink-0" />
                              <span className="text-sm text-green-700">{workflow}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                  {/* Dependencies */}
                  {node.semantic_metadata.dependencies_description && (
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Dependencies</label>
                      <p className="text-sm text-slate-700 bg-purple-50 p-3 rounded-lg border border-purple-200">
                        {node.semantic_metadata.dependencies_description}
                      </p>
                    </div>
                  )}
                </>
              )}

              {/* Action Info */}
              <div className="space-y-2 pt-4 border-t border-slate-200">
                <h3 className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Action</h3>
                <div className="text-sm text-slate-600">
                  <span className="font-semibold">{node.action_kind}</span>
                </div>
                {node.target_id && (
                  <div className="text-xs text-slate-500 font-mono bg-slate-50 p-2 rounded truncate">
                    {node.target_id}
                  </div>
                )}
              </div>
      </div>
    </motion.div>
  )
}

export default SemanticPanel
