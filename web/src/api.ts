/** Typed client for the craftflip API. The SPA and the API share one origin. */

export interface IngredientCost {
  item: string
  displayName: string
  unitPrice: number
  source: 'listing' | 'market'
  via: string
  optionsConsidered: number
  count: number
  subtotal: number
}

export interface OutputValue {
  item: string
  displayName: string
  count: number
  unitPrice: number
  source: 'market' | 'listing'
  total: number
  cheapestListing: number | null
  cheapestListingAt: string | null
  volume24h: number
  sales24h: number
  itemId: string | null
}

export interface Flip {
  item: string
  displayName: string
  recipeId: string
  recipeType: 'crafting_shaped' | 'crafting_shapeless' | string
  cost: number
  revenue: number
  fee: number
  profit: number
  margin: number
  outputCount: number
  costPerUnit: number
  profitPerUnit: number
  estimated: boolean
  /** every material is buyable right now, so this flip can actually be executed */
  actionable: boolean
  materialsTotal: number
  materialsListed: number
  /** other recipes produce this same item; this row is the best of them */
  alternates: number
  ingredients: IngredientCost[]
  output: OutputValue
  listedNow: number | null
  listedAt: string | null
}

export interface CraftsMeta {
  recipesConsidered: number
  flipsFound: number
  computedAt: string | null
  feePercent: number
  indexAgeSeconds: number | null
  upstreamOk: boolean
  indexSize: number
}

export interface CraftsResponse {
  count: number
  items: Flip[]
  meta: CraftsMeta
}

export interface GridCell {
  item: string | null
  displayName: string | null
  unitPrice: number | null
  tag: string | null
}

export interface Grid {
  type: string
  size: number | null
  cells: (GridCell | null)[][] | null
  /** shapeless recipes have no arrangement, but their slots still get priced */
  slots?: (GridCell & { count: number })[] | null
}

export interface Sale {
  price: number | null
  itemCount: number | null
  seller: string | null
  at: string | null
}

export interface Detail {
  item: string
  displayName: string
  flip: Flip | null
  craftable: boolean
  grid?: Grid
  recipeId?: string
  recipeType?: string
  unpriced?: string
  recentSales?: Sale[]
  recentSalesError?: string
}

export interface HistoryPoint {
  at: string
  profit: number
  margin: number
}

export interface HistoryResponse {
  item: string
  days: number
  points: HistoryPoint[]
  available: boolean
  note: string | null
}

export interface StatusResponse {
  service: string
  version: string
  upstream: string
  market: {
    indexSize: number
    needed: number
    missingCount: number
    missingSample: string[]
    ageSeconds: number | null
    builtAt: string | null
    buildSeconds: number | null
    requestsUsed: number
    upstreamOk: boolean
    lastError: string | null
  }
  table: { recipesConsidered: number; flipsFound: number; computedAt: string | null; feePercent: number }
  history: { available: boolean; dir: string; topN: number; writes: number; lastError: string | null }
  recipes: { mcVersion: string | null; generatedAt: string | null; sha256: string | null } | null
  recipesError: string | null
  config: { indexTtlSeconds: number; flipsTtlSeconds: number; feePercent: number }
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* response was not JSON; keep the status line */
    }
    throw new Error(detail)
  }
  return (await r.json()) as T
}

export const api = {
  crafts: (limit = 500) => get<CraftsResponse>(`/api/crafts?limit=${limit}`),
  detail: (item: string) => get<Detail>(`/api/crafts/${encodeURIComponent(item)}`),
  history: (item: string, days = 14) =>
    get<HistoryResponse>(`/api/crafts/${encodeURIComponent(item)}/history?days=${days}`),
  status: () => get<StatusResponse>('/api/status'),
}
