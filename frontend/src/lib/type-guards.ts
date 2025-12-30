import type { NavigationNode, Component } from "./api"

/**
 * Type guard to check if an object is a NavigationNode
 */
export function isNavigationNode(obj: any): obj is NavigationNode {
  return "title" in obj && "node_type" in obj
}

/**
 * Type guard to check if an object is a Component
 */
export function isComponent(obj: any): obj is Component {
  return "module_name" in obj && "component_id" in obj
}
