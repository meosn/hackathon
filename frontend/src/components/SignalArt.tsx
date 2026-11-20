import { useEffect, useRef } from 'react'

/** Parallel contour lines form the edition artwork. No audio data is implied. */
export function SignalArt({
  variant = 0,
  mini = false,
}: {
  variant?: number
  mini?: boolean
}) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const paint = () => {
      const box = canvas.getBoundingClientRect()
      if (!box.width || !box.height) return
      const scale = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(box.width * scale)
      canvas.height = Math.round(box.height * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.scale(scale, scale)
      const w = box.width,
        h = box.height,
        radius = mini
          ? Math.min(w * 0.73, h * 0.94)
          : Math.min(w * 0.45, h * 0.53)
      const colors = [
        ['#34251a', '#e3a865', '#fff4be'],
        ['#173c39', '#71bea0', '#d8ffab'],
        ['#342a42', '#b699d3', '#f4d1f5'],
        ['#233344', '#87afce', '#ebeee0'],
      ]
      const [dark, mid, bright] = colors[variant % colors.length]
      const centerX = w * 0.56,
        centerY = h * (mini ? 0.57 : 0.55)
      const glow = ctx.createRadialGradient(
        centerX,
        centerY,
        0,
        centerX,
        centerY,
        radius * 1.45
      )
      glow.addColorStop(0, dark)
      glow.addColorStop(0.72, dark + '80')
      glow.addColorStop(1, dark + '00')
      ctx.fillStyle = glow
      ctx.fillRect(0, 0, w, h)
      ctx.translate(centerX, centerY)
      ctx.rotate(((variant % 3) - 1) * 0.15 - 0.24)
      const tilt = 0.34
      const lines = mini ? 44 : 94
      for (let i = 0; i < lines; i++) {
        const lat = ((i + 0.5) / lines) * Math.PI - Math.PI / 2
        const ring = Math.cos(lat),
          a = Math.sin(lat)
        ctx.beginPath()
        for (let j = 0; j <= 160; j++) {
          const lon = (j / 160) * Math.PI * 2
          const modulation =
            1 +
            0.12 * Math.sin(lon * 3 + lat * 3.2 + variant) +
            0.09 * Math.sin(lon * 5 - lat * 2 + 0.5 * variant) +
            0.1 * Math.cos(lat * 6 + lon * 1.9)
          const x = ring * Math.cos(lon) * modulation
          const depth = ring * Math.sin(lon) * modulation
          const y = a * (1 + 0.14 * Math.sin(lon * 3) * ring)
          const py =
            (y * Math.cos(tilt) - depth * Math.sin(tilt)) * radius * 0.84
          if (j === 0) ctx.moveTo(x * radius, py)
          else ctx.lineTo(x * radius, py)
        }
        const lum = Math.sin((i / lines) * Math.PI)
        ctx.globalAlpha = mini ? 0.79 : 0.48 + 0.46 * lum
        ctx.lineWidth = mini ? 0.78 : 1.15
        ctx.strokeStyle = i / lines < 0.35 ? bright : mid
        ctx.stroke()
      }
    }
    paint()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(paint)
    observer.observe(canvas)
    return () => observer.disconnect()
  }, [variant, mini])
  return (
    <canvas
      ref={ref}
      className={'signal-art' + (mini ? ' mini' : '')}
      aria-hidden="true"
    />
  )
}
