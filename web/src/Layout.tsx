import { Link, Outlet } from 'react-router-dom'
import { api } from './api'
import { ageSeconds, count } from './format'
import { usePoll, useTicker } from './hooks'

/** The masthead carries the live state of the index: how big it is, how old it is,
 *  and whether the last upstream refresh actually worked. */
export default function Layout() {
  const { data, error } = usePoll<Awaited<ReturnType<typeof api.status>>>('/api/status', 30_000)
  useTicker(1000)

  const market = data?.market
  const degraded = Boolean(error) || (market ? !market.upstreamOk : false)

  return (
    <div className="shell">
      <header className="masthead">
        <h1 className="wordmark">
          Craft<span>flip</span>
        </h1>
        <p className="tagline">
          Every vanilla crafting recipe, costed against live donut.auction prices.
        </p>
        <div className="livestrip">
          <span className="pip">
            index <span className="v">{count(market?.indexSize ?? 0)}</span>
          </span>
          <span className="pip">
            age <span className="v">{ageSeconds(market?.ageSeconds)}</span>
          </span>
          <span className="pip">
            recipes <span className="v">{count(data?.table.recipesConsidered ?? 0)}</span>
          </span>
          <span className={`pip ${degraded ? 'degraded' : ''}`}>
            <span className="dot" aria-hidden="true" />
            {degraded ? 'upstream degraded' : 'live'}
          </span>
        </div>
      </header>

      <Outlet context={{ status: data, statusError: error }} />
    </div>
  )
}

export function BackLink({ to = '/' }: { to?: string }) {
  return (
    <Link className="backlink" to={to}>
      ← Ledger
    </Link>
  )
}
