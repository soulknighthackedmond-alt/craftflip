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

export interface ConfidenceFactor {
  key: string
  label: string
  /** 0-1, this factor's own reading */
  score: number
  weight: number
  /** points this factor contributed to the final 0-100 score */
  contribution: number
  detail: string
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
  /** what the server's /sell pays for this item: its base price times your own
   *  multiplier for it. Null when the item has no entry in the price table --
   *  absent means unknown, not zero. */
  instasellUnitPrice: number | null
  instasellRevenue: number | null
  instasellFee: number | null
  instasellProfit: number | null
  instasellMargin: number | null
  instasellBasis: string | null
  instasellBasePrice: number | null
  instasellMultiplier: number | null
  /** where the base price came from: in-game (/worth), wiki or community */
  instasellSource: 'in-game' | 'wiki' | 'community' | null
  instasellNote: string | null
  /** the market exit instead: the median price this item actually sold at.
   *  Null until the sales index has looked the item up. */
  dumpUnitPrice: number | null
  dumpRevenue: number | null
  dumpProfit: number | null
  dumpMargin: number | null
  dumpBasis: string | null
  dumpSales: number | null
  dumpLastAt: string | null
  /** 0-100, how much the inputs behind this row can be trusted */
  confidence: number
  confidenceLabel: 'high' | 'medium' | 'low' | 'very low'
  confidenceFactors: ConfidenceFactor[]
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
  /** price per unit -- one sale can cover a whole stack */
  unitPrice: number | null
  seller: string | null
  at: string | null
}

/** What the completed sales say about the price an item actually clears at. */
export interface SalesSummary {
  sales: number
  priced: number
  low?: number
  median?: number
  high?: number
  last?: number | null
  lastAt?: string | null
}

export interface SellPrice {
  base: number
  multiplier: number
  payout: number
  source: 'in-game' | 'wiki' | 'community' | null
  note: string | null
}

export interface Detail {
  item: string
  displayName: string
  flip: Flip | null
  craftable: boolean
  /** the fixed /sell price for this item, if the table has one */
  sellPrice?: SellPrice | null
  grid?: Grid
  recipeId?: string
  recipeType?: string
  unpriced?: string
  recentSales?: Sale[]
  salesSummary?: SalesSummary
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
  sales: {
    priced: number
    tracked: number
    basis: string
    ttlSeconds: number
    requests: number
    lastError: string | null
  }
  /** the fixed /sell price table, and whether the volume copy is in play */
  sellPrices: {
    items: number
    multiplier: number
    tablePath: string | null
    tableExists: boolean
    seedPath: string | null
    sources: string[]
    errors: string[]
    revision: number
  }
  history: { available: boolean; dir: string; topN: number; writes: number; lastError: string | null }
  recipes: { mcVersion: string | null; generatedAt: string | null; sha256: string | null } | null
  recipesError: string | null
  config: {
    indexTtlSeconds: number
    flipsTtlSeconds: number
    feePercent: number
    sellMultiplier: number
  }
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
