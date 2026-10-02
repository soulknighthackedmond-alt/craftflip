/** Number and time formatting. Every figure in the UI goes through here so the
 *  ledger reads consistently down a column. */

const UNITS: [number, string][] = [
  [1e12, 'T'],
  [1e9, 'B'],
  [1e6, 'M'],
  [1e3, 'K'],
]

/** Compact coin figure for scanning. Full value belongs in the title attribute. */
export function coins(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  for (const [scale, suffix] of UNITS) {
    if (abs >= scale) {
      const v = abs / scale
      return `${sign}${v.toFixed(v < 10 ? 2 : v < 100 ? 1 : 0)}${suffix}`
    }
  }
  if (abs >= 100) return `${sign}${Math.round(abs).toLocaleString('en-GB')}`
  return `${sign}${abs.toFixed(abs < 10 ? 2 : 1)}`
}

/** Exact figure, for tooltips and detail panes. */
export function coinsExact(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  return `${n < 0 ? '-' : ''}${Math.abs(n).toLocaleString('en-GB', {
    maximumFractionDigits: 2,
  })}`
}

export function pct(m: number | null | undefined, digits = 1): string {
  if (m === null || m === undefined || !Number.isFinite(m)) return '—'
  return `${(m * 100).toFixed(digits)}%`
}

export function count(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  return n.toLocaleString('en-GB')
}

/** Human age from an ISO timestamp, or from a seconds value. */
export function ageFrom(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return '—'
  return ageSeconds((Date.now() - t) / 1000)
}

export function ageSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined || !Number.isFinite(s)) return '—'
  if (s < 60) return `${Math.max(0, Math.round(s))}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** netherite_ingot -> Netherite Ingot, for anything the API did not pre-title. */
export function titleise(name: string): string {
  return name
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
