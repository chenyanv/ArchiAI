"use client"

import { useEffect, useRef } from "react"

interface Node {
  x: number
  y: number
  vx: number
  vy: number
}

export function GraphBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext("2d")
    if (!ctx) return

    let animationId: number

    const resizeCanvas = () => {
      const parent = canvas.parentElement
      if (parent) {
        canvas.width = parent.offsetWidth
        canvas.height = parent.offsetHeight
      }
    }
    resizeCanvas()
    window.addEventListener("resize", resizeCanvas)

    // Create nodes
    const nodeCount = 50
    const nodes: Node[] = []
    for (let i = 0; i < nodeCount; i++) {
      nodes.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
      })
    }

    // Animation loop
    const animate = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // Update and draw nodes
      nodes.forEach((node) => {
        // Update position
        node.x += node.vx
        node.y += node.vy

        // Bounce off edges
        if (node.x < 0 || node.x > canvas.width) node.vx *= -1
        if (node.y < 0 || node.y > canvas.height) node.vy *= -1

        // Keep nodes in bounds
        node.x = Math.max(0, Math.min(canvas.width, node.x))
        node.y = Math.max(0, Math.min(canvas.height, node.y))

        // Draw node with gradient
        const gradient = ctx.createRadialGradient(node.x - 1, node.y - 1, 0, node.x, node.y, 3)
        gradient.addColorStop(0, "rgba(60, 60, 60, 0.5)")
        gradient.addColorStop(0.5, "rgba(30, 30, 30, 0.4)")
        gradient.addColorStop(1, "rgba(0, 0, 0, 0.2)")

        ctx.beginPath()
        ctx.arc(node.x, node.y, 3, 0, Math.PI * 2)
        ctx.fillStyle = gradient
        ctx.fill()

        // Add shadow
        ctx.shadowColor = "rgba(0, 0, 0, 0.15)"
        ctx.shadowBlur = 2
        ctx.shadowOffsetX = 1
        ctx.shadowOffsetY = 1
        ctx.fill()
        ctx.shadowColor = "transparent"
        ctx.shadowBlur = 0
        ctx.shadowOffsetX = 0
        ctx.shadowOffsetY = 0
      })

      // Draw connections
      ctx.lineWidth = 1
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x
          const dy = nodes[i].y - nodes[j].y
          const distance = Math.sqrt(dx * dx + dy * dy)

          // Only draw connection if nodes are close
          if (distance < 150) {
            ctx.beginPath()
            ctx.moveTo(nodes[i].x, nodes[i].y)
            ctx.lineTo(nodes[j].x, nodes[j].y)
            const opacity = ((150 - distance) / 150) * 0.4
            ctx.strokeStyle = `rgba(0, 0, 0, ${Math.max(0.12, opacity)})`
            ctx.stroke()
          }
        }
      }

      animationId = requestAnimationFrame(animate)
    }

    animate()

    return () => {
      window.removeEventListener("resize", resizeCanvas)
      cancelAnimationFrame(animationId)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      style={{ zIndex: 0, opacity: 0.6 }}
      aria-hidden="true"
    />
  )
}
