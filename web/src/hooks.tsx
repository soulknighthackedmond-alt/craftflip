import { useEffect, useRef, useState } from 'react'

/** Poll a JSON endpoint on an interval. Keeps the last good payload on error so a
 *  blip never blanks the ledger. */
export function usePoll<T>(url: string, intervalMs: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    let timer: number | undefined

    const tick = async () => {
      try {
        const r = await fetch(url, { headers: { Accept: 'application/json' } })
        if (!r.ok) {
          let detail = `${r.status} ${r.statusText}`
          try {
            const body = await r.json()
            if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : detail
          } catch {
            /* not JSON */
          }
          throw new Error(detail)
        }
        const json = (await r.json()) as T
        if (alive) {
          setData(json)
          setError(null)
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      } finally {
        if (alive) {
          setLoading(false)
          timer = window.setTimeout(tick, intervalMs)
        }
      }
    }

    tick()
    return () => {
      alive = false
      if (timer) window.clearTimeout(timer)
    }
  }, [url, intervalMs])

  return { data, error, loading }
}

/** A number that flashes once when its value changes, so movement down a column
 *  is visible without animating constantly. */
export function Num({
  value,
  format,
  className = '',
  title,
}: {
  value: number | null | undefined
  format?: (n: number) => string
  className?: string
  title?: string
}) {
  const prev = useRef<number | null | undefined>(undefined)
  const changed = prev.current !== undefined && prev.current !== value
  useEffect(() => {
    prev.current = value
  }, [value])

  const shown =
    value === null || value === undefined || !Number.isFinite(value)
      ? '—'
      : format
        ? format(value)
        : String(value)

  return (
    <span key={String(value)} className={`num ${changed ? 'flash' : ''} ${className}`} title={title}>
      {shown}
    </span>
  )
}

/** A ticking "how old is this" readout that does not need the server to re-send. */
export function useTicker(intervalMs = 1000): number {
  const [, force] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => force((n) => n + 1), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return Date.now()
}
