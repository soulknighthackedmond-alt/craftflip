import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { type CraftsResponse, type Flip } from '../api'
import Ledger, { type SortKey } from '../components/Ledger'
import { coins, coinsExact, count, pct, titleise } from '../format'
import { Num, usePoll } from '../hooks'

export default function LedgerPage() {
  const { data, error, loading } = usePoll<CraftsResponse>('/api/crafts?limit=500', 30_000)

  const [q, setQ] = useState('')
  const [minProfit, setMinProfit] = useState('')
  const [minMargin, setMinMargin] = useState('')
  const [minConf, setMinConf] = useState('')
  const [profitableOnly, setProfitableOnly] = useState(true)
  const [buyableOnly, setBuyableOnly] = useState(false)
  const [instasellOnly, setInstasellOnly] = useState(false)
  const [sort, setSort] = useState<SortKey>('profit')

  const all = data?.items ?? []

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase().replace(/\s+/g, '_')
    const mp = minProfit.trim() === '' ? null : Number(minProfit)
    const mm = minMargin.trim() === '' ? null : Number(minMargin) / 100
    const mc = minConf.trim() === '' ? null : Number(minConf)

    let out: Flip[] = all
    if (needle) out = out.filter((f) => f.item.includes(needle))
    if (mp !== null && Number.isFinite(mp)) out = out.filter((f) => f.profit >= mp)
    if (mm !== null && Number.isFinite(mm)) out = out.filter((f) => f.margin >= mm)
    if (mc !== null && Number.isFinite(mc)) out = out.filter((f) => f.confidence >= mc)
    if (profitableOnly && mp === null) out = out.filter((f) => f.profit > 0)
    if (buyableOnly) out = out.filter((f) => f.actionable)
    if (instasellOnly) out = out.filter((f) => (f.instasellProfit ?? 0) > 0)

    const key = (f: Flip) =>
      sort === 'item'
        ? f.item
        : sort === 'instasellProfit'
          ? (f.instasellProfit ?? Number.NEGATIVE_INFINITY)
          : (f[sort] as number)
    return [...out].sort((a, b) =>
      sort === 'item'
        ? String(key(a)).localeCompare(String(key(b)))
        : (key(b) as number) - (key(a) as number),
    )
  }, [all, q, minProfit, minMargin, minConf, profitableOnly, buyableOnly, instasellOnly, sort])

  // The spread states the whole market, not the filtered view. Margins from
  // estimated costs are excluded when there is anything genuinely buyable, since a
  // 5000% margin built on an item nobody is selling is noise, not a flip.
  const spread = useMemo(() => {
    const profitable = all.filter((f) => f.profit > 0)
    const buyable = profitable.filter((f) => f.actionable)
    const basis = buyable.length > 0 ? buyable : profitable
    const bestMargin = basis.reduce<Flip | null>(
      (best, f) => (best === null || f.margin > best.margin ? f : best),
      null,
    )
    const biggest = basis.reduce<Flip | null>(
      (best, f) => (best === null || f.profit > best.profit ? f : best),
      null,
    )
    // instasell: a row only counts when it still profits at the price the server
    // actually pays for it. That is a guaranteed exit, so it is the strictest
    // measure here -- most items have no published /sell price at all.
    const instasold = profitable.filter((f) => (f.instasellProfit ?? 0) > 0)
    const instasoldBest = instasold.reduce<Flip | null>(
      (best, f) =>
        best === null || (f.instasellProfit ?? 0) > (best.instasellProfit ?? 0) ? f : best,
      null,
    )
    // and the softer measure: still profits at the median price it has actually
    // sold for lately, which needs a buyer but needs no fixed server price
    const dumpable = profitable.filter((f) => (f.dumpProfit ?? 0) > 0)
    const priced = profitable.filter((f) => f.instasellProfit !== null)
    const avgConfidence =
      profitable.length > 0
        ? profitable.reduce((sum, f) => sum + f.confidence, 0) / profitable.length
        : 0
    return {
      buyable: buyable.length,
      estimatedOnly: profitable.length - buyable.length,
      bestMargin,
      biggest,
      instasellable: instasold.length,
      instasoldBest,
      priced: priced.length,
      dumpable: dumpable.length,
      avgConfidence,
      usingEstimated: buyable.length === 0,
    }
  }, [all])

  const meta = data?.meta

  return (
    <>
      <section className="spread" aria-label="market summary">
        <div>
          <span className="k">Flips you can do right now</span>
          <span className="v accent">
            <Num value={spread.buyable} format={(n) => count(n)} />
          </span>
          <div className="sub">
            every material listed on the auction house · {count(spread.estimatedOnly)} more
            priced from market value only
          </div>
        </div>
        <div>
          <span className="k">Best margin</span>
          <span className="v accent">
            <Num value={spread.bestMargin?.margin ?? null} format={(n) => pct(n)} />
          </span>
          <div className="sub">
            {spread.bestMargin ? (
              <>
                <Link to={`/item/${spread.bestMargin.item}`}>
                  {titleise(spread.bestMargin.item)}
                </Link>
                {spread.usingEstimated ? ' · estimated costs' : ''}
              </>
            ) : (
              'nothing is profitable right now'
            )}
          </div>
        </div>
        <div>
          <span className="k">Biggest single flip</span>
          <span className="v">
            <Num value={spread.biggest?.profit ?? null} format={(n) => coins(n)} />
          </span>
          <div className="sub">
            {spread.biggest ? (
              <Link to={`/item/${spread.biggest.item}`}>
                {titleise(spread.biggest.item)} — {coinsExact(spread.biggest.profit)} per craft
              </Link>
            ) : (
              'no profitable craft in the current index'
            )}
          </div>
        </div>
        <div>
          <span className="k">Profitable if instasold</span>
          <span className="v accent">
            <Num value={spread.instasellable} format={(n) => count(n)} />
          </span>
          <div className="sub">
            {spread.instasoldBest ? (
              <>
                best{' '}
                <Link to={`/item/${spread.instasoldBest.item}`}>
                  {titleise(spread.instasoldBest.item)}
                </Link>{' '}
                — {coinsExact(spread.instasoldBest.instasellProfit ?? 0)} at the server's /sell
                price
              </>
            ) : (
              <>
                nothing clears the server's /sell price yet · {count(spread.dumpable)} would at
                the median recent sale
              </>
            )}
            {' · '}
            {count(spread.priced)} of {count(spread.estimatedOnly + spread.buyable)} items have a
            published /sell price
          </div>
        </div>
        <div>
          <span className="k">Average confidence</span>
          <span className="v">
            <Num value={spread.avgConfidence} format={(n) => `${Math.round(n)}%`} />
          </span>
          <div className="sub">
            across every profitable row · hover the bar in any row for the breakdown
          </div>
        </div>
      </section>

      <div className="controls">
        <div className="field grow">
          <label htmlFor="q">Find an item</label>
          <input
            id="q"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="netherite_ingot"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="mp">Min profit</label>
          <input
            id="mp"
            value={minProfit}
            onChange={(e) => setMinProfit(e.target.value)}
            placeholder="any"
            inputMode="numeric"
          />
        </div>
        <div className="field">
          <label htmlFor="mm">Min margin %</label>
          <input
            id="mm"
            value={minMargin}
            onChange={(e) => setMinMargin(e.target.value)}
            placeholder="any"
            inputMode="numeric"
          />
        </div>
        <div className="field">
          <label htmlFor="mc">Min confidence %</label>
          <input
            id="mc"
            value={minConf}
            onChange={(e) => setMinConf(e.target.value)}
            placeholder="any"
            inputMode="numeric"
            title="how much the row's inputs can be trusted, 0-100"
          />
        </div>
        <label className="toggle">
          <input
            type="checkbox"
            checked={profitableOnly}
            onChange={(e) => setProfitableOnly(e.target.checked)}
          />
          profitable only
        </label>
        <label className="toggle" title="only flips whose every material has a live listing">
          <input
            type="checkbox"
            checked={buyableOnly}
            onChange={(e) => setBuyableOnly(e.target.checked)}
          />
          buyable now
        </label>
        <label
          className="toggle"
          title="only flips that still profit at the price the server pays for them via /sell"
        >
          <input
            type="checkbox"
            checked={instasellOnly}
            onChange={(e) => setInstasellOnly(e.target.checked)}
          />
          instasell ok
        </label>
        <span className="spacer" />
        <span className="count-line">
          {loading && !data
            ? 'loading…'
            : `${count(rows.length)} of ${count(all.length)} shown`}
        </span>
      </div>

      {error && !data ? (
        <div className="note">
          <h3>The API did not answer</h3>
          <p>
            {error}. If the container just started it is still building its first market
            index — that takes a couple of minutes. Otherwise check{' '}
            <code>/api/status</code>.
          </p>
        </div>
      ) : null}

      {loading && !data ? (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      ) : null}

      {data && all.length === 0 ? (
        <div className="note">
          <h3>No recipe could be costed</h3>
          <p>
            The market index is {count(meta?.indexSize ?? 0)} items
            {meta?.indexSize === 0 ? ' — the first refresh has not finished, or upstream is down' : ''}.
            Check <code>/api/status</code> for what the last refresh reported.
          </p>
        </div>
      ) : null}

      {data && all.length > 0 && rows.length === 0 ? (
        <div className="note">
          <h3>Nothing clears that bar</h3>
          <p>
            {count(all.length)} recipes are costed, but none match this filter. Clear the
            search, lower the minimum profit, or untick profitable only.
          </p>
        </div>
      ) : null}

      {rows.length > 0 ? <Ledger rows={rows} sort={sort} onSort={setSort} /> : null}
    </>
  )
}
