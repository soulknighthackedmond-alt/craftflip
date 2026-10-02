import type { HistoryPoint } from '../api'
import { coins, pct, shortDate } from '../format'

/** Hand-rolled profit history. No chart library for one line. */
export default function Sparkline({ points }: { points: HistoryPoint[] }) {
  if (points.length < 2) return null

  const W = 620
  const H = 120
  const PAD = { l: 8, r: 8, t: 14, b: 20 }

  const profits = points.map((p) => p.profit)
  const lo = Math.min(...profits, 0)
  const hi = Math.max(...profits, 0)
  const span = hi - lo || 1

  const x = (i: number) => PAD.l + (i / (points.length - 1)) * (W - PAD.l - PAD.r)
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b)

  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.profit).toFixed(1)}`).join(' ')
  const area = `${line} L${x(points.length - 1).toFixed(1)},${y(lo).toFixed(1)} L${x(0).toFixed(1)},${y(lo).toFixed(1)} Z`

  const last = points[points.length - 1]

  return (
    <div>
      <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`Profit history, ${points.length} samples, latest ${coins(last.profit)}`}>
        {lo < 0 && hi > 0 ? <line className="zero" x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} /> : null}
        <path className="area" d={area} />
        <path className="line" d={line} />
        <line className="axis" x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} />
        <text className="lbl" x={PAD.l} y={H - 6}>
          {shortDate(points[0].at)}
        </text>
        <text className="lbl" x={W - PAD.r} y={H - 6} textAnchor="end">
          {shortDate(last.at)}
        </text>
        <text className="lbl" x={PAD.l} y={10}>
          peak {coins(hi)}
        </text>
      </svg>
      <div className="grid-note" style={{ maxWidth: 'none' }}>
        {points.length} samples · latest profit {coins(last.profit)} ({pct(last.margin)})
      </div>
    </div>
  )
}
