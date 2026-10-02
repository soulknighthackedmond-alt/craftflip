import { useParams } from 'react-router-dom'
import { type Detail, type HistoryResponse } from '../api'
import CraftGrid from '../components/CraftGrid'
import Sparkline from '../components/Sparkline'
import { BackLink } from '../Layout'
import { ageFrom, ageSeconds, coins, coinsExact, count, pct, shortDate, titleise } from '../format'
import { usePoll } from '../hooks'

export default function ItemPage() {
  const { name = '' } = useParams()
  const detail = usePoll<Detail>(`/api/crafts/${encodeURIComponent(name)}`, 30_000)
  const history = usePoll<HistoryResponse>(
    `/api/crafts/${encodeURIComponent(name)}/history?days=14`,
    60_000,
  )

  const d = detail.data
  const flip = d?.flip ?? null
  const up = (flip?.profit ?? 0) >= 0

  return (
    <>
      <BackLink />

      <div className="detail-head">
        <h1>{d?.displayName ?? titleise(name)}</h1>
        {d?.recipeId ? <span className="id">{d.recipeId}</span> : null}
        {flip ? (
          <span className={`num ${up ? 'profit up' : 'profit down'}`} style={{ marginLeft: 'auto', fontSize: 22 }}>
            {coinsExact(flip.profit)}
          </span>
        ) : null}
      </div>

      {detail.error && !d ? (
        <div className="note">
          <h3>Could not load this item</h3>
          <p>{detail.error}</p>
        </div>
      ) : null}

      {d && !d.craftable && !flip ? (
        <div className="note">
          <h3>Not a crafting recipe</h3>
          <p>
            Nothing in the vanilla 1.21.11 recipe set produces {titleise(name)}. It may
            still be tradeable — the ledger only covers craftable items.
          </p>
        </div>
      ) : null}

      {d ? (
        <div className="detail-body">
          <div>
            {d.unpriced ? (
              <div className="note" style={{ paddingTop: 0 }}>
                <h3>Cannot be costed</h3>
                <p>{d.unpriced}</p>
              </div>
            ) : null}

            {flip ? (
              <>
                <div className="panel">
                  <h4>Materials to buy</h4>
                  <table className="sales">
                    <thead>
                      <tr>
                        <th>Item</th>
                        <th className="r">Qty</th>
                        <th className="r">Unit</th>
                        <th className="r">Subtotal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {flip.ingredients.map((ing) => (
                        <tr key={`${ing.item}-${ing.via}`}>
                          <td className="n">
                            {titleise(ing.item)}
                            {ing.via !== 'item' && ing.via !== 'choice' ? (
                              <span style={{ color: 'var(--muted-dim)' }}> · any {ing.via}</span>
                            ) : null}
                            {ing.source === 'market' ? (
                              <span style={{ color: 'var(--muted-dim)' }}> · estimated</span>
                            ) : null}
                          </td>
                          <td className="r">{ing.count}</td>
                          <td className="r" title={coinsExact(ing.unitPrice)}>
                            {coins(ing.unitPrice)}
                          </td>
                          <td className="r" title={coinsExact(ing.subtotal)}>
                            {coins(ing.subtotal)}
                          </td>
                        </tr>
                      ))}
                      <tr>
                        <td className="n">Materials</td>
                        <td className="r" />
                        <td className="r" />
                        <td className="r">{coinsExact(flip.cost)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div className="panel">
                  <h4>The arithmetic</h4>
                  <div className="ledger-math">
                    <div className="mline">
                      <span className="k">Cost to craft</span>
                      <span className="v">{coinsExact(flip.cost)}</span>
                    </div>
                    {flip.fee > 0 ? (
                      <div className="mline">
                        <span className="k">Auction fee</span>
                        <span className="v">{coinsExact(flip.fee)}</span>
                      </div>
                    ) : null}
                    <div className="mline">
                      <span className="k">
                        Sells for ({flip.outputCount}× at market value)
                      </span>
                      <span className="v">{coinsExact(flip.revenue)}</span>
                    </div>
                    <div className={`mline total ${up ? 'up' : 'down'}`}>
                      <span className="k">Profit per craft</span>
                      <span className="v">{coinsExact(flip.profit)}</span>
                    </div>
                    <div className="mline">
                      <span className="k">Margin</span>
                      <span className="v">{pct(flip.margin)}</span>
                    </div>
                    <div className="mline">
                      <span className="k">Profit per unit</span>
                      <span className="v">{coinsExact(flip.profitPerUnit)}</span>
                    </div>
                    <div className="mline">
                      <span className="k">
                        Instasell ({flip.instasellBasis ?? 'no recent sales'})
                      </span>
                      <span className="v">
                        {flip.instasellRevenue === null ? '—' : coinsExact(flip.instasellRevenue)}
                      </span>
                    </div>
                    <div
                      className={`mline total ${
                        flip.instasellProfit === null ? '' : flip.instasellProfit >= 0 ? 'up' : 'down'
                      }`}
                    >
                      <span className="k">Instasell profit</span>
                      <span className="v">
                        {flip.instasellProfit === null ? '—' : coinsExact(flip.instasellProfit)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="panel">
                  <h4>Recent sales</h4>
                  {d.recentSales && d.recentSales.length > 0 ? (
                    <>
                      {d.salesSummary && d.salesSummary.priced > 0 ? (
                        <div className="sales-sum">
                          <span>
                            <b>{count(d.salesSummary.sales)}</b> on record
                          </span>
                          <span>
                            clears at <b>{coins(d.salesSummary.median)}</b> median
                          </span>
                          <span>
                            low <b>{coins(d.salesSummary.low)}</b>
                          </span>
                          <span>
                            high <b>{coins(d.salesSummary.high)}</b>
                          </span>
                          <span>
                            newest{' '}
                            {d.salesSummary.lastAt ? `${ageFrom(d.salesSummary.lastAt)} ago` : '—'}
                          </span>
                        </div>
                      ) : null}
                      <table className="sales">
                        <thead>
                          <tr>
                            <th>Buyer paid</th>
                            <th className="r">Qty</th>
                            <th className="r">Each</th>
                            <th>Seller</th>
                            <th className="r">When</th>
                          </tr>
                        </thead>
                        <tbody>
                          {d.recentSales.map((s, i) => (
                            <tr key={i}>
                              <td title={coinsExact(s.price)}>{coins(s.price)}</td>
                              <td className="r">{s.itemCount ?? '—'}</td>
                              <td className="r" title={coinsExact(s.unitPrice)}>
                                {coins(s.unitPrice)}
                              </td>
                              <td className="n">{s.seller ?? '—'}</td>
                              <td className="r" title={shortDate(s.at)}>
                                {s.at ? `${ageFrom(s.at)} ago` : '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </>
                  ) : (
                    <div className="grid-note" style={{ marginTop: 0, maxWidth: 'none' }}>
                      {d.recentSalesError
                        ? `Could not reach the sales feed: ${d.recentSalesError}`
                        : 'No completed sales on record for this item.'}
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </div>

          <div>
            {d.grid ? (
              <div className="panel">
                <h4>Recipe</h4>
                <CraftGrid grid={d.grid} output={d.item} />
              </div>
            ) : null}

            <div className="panel">
              <h4>Profit history</h4>
              {history.data && history.data.points.length >= 2 ? (
                <Sparkline points={history.data.points} />
              ) : (
                <div className="grid-note" style={{ marginTop: 0, maxWidth: 'none' }}>
                  {history.data?.note ??
                    'History is still building — a point is recorded each time the index refreshes.'}
                </div>
              )}
            </div>

            {flip ? (
              <div className="panel">
                <h4>Market</h4>
                <div className="ledger-math">
                  <div className="mline">
                    <span className="k">Market value</span>
                    <span className="v">{coinsExact(flip.output.unitPrice)}</span>
                  </div>
                  <div className="mline">
                    <span className="k">Cheapest listed now</span>
                    <span className="v">
                      {flip.listedNow === null ? 'nothing listed' : coinsExact(flip.listedNow)}
                    </span>
                  </div>
                  <div className="mline">
                    <span className="k">Listing seen</span>
                    <span className="v">
                      {flip.listedAt ? `${shortDate(flip.listedAt)} (${ageSeconds(
                        (Date.now() - Date.parse(flip.listedAt)) / 1000,
                      )} ago)` : '—'}
                    </span>
                  </div>
                  <div className="mline">
                    <span className="k">Sales 24h</span>
                    <span className="v">
                      {count(flip.output.sales24h)} · {coins(flip.output.volume24h)} volume
                    </span>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </>
  )
}
