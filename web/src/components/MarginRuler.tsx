import { Num } from '../hooks'
import { pct } from '../format'

/** Full-width reference for the ruler: a 25% margin fills the track. Anything
 *  beyond that pins at full, and the exact figure is always printed beside it. */
const FULL = 0.25

export default function MarginRuler({ margin }: { margin: number }) {
  const down = margin < 0
  const width = Math.min(1, Math.abs(margin) / FULL) * 100

  return (
    <span className={`ruler margin ${down ? 'down' : ''}`}>
      <span className="track" aria-hidden="true">
        <span className="fill" style={{ width: `${width}%` }} />
      </span>
      <Num value={margin} format={(n) => pct(n)} className="pc" />
    </span>
  )
}
