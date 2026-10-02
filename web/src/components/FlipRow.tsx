import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Flip, type Grid } from '../api'
import { ageFrom, ageSeconds, coins, coinsExact, pct, titleise } from '../format'
import { Num } from '../hooks'
import Confidence from './Confidence'
import CraftGrid from './CraftGrid'
import MarginRuler from './MarginRuler'

/** One ledger line. Clicking it unfolds the bill of materials in place: what to
 *  buy, what the grid looks like, and the arithmetic that turns one into the other. */
export default function FlipRow({ flip }: { flip: Flip }) {
  const [open, setOpen] = useState(false)
  const [grid, setGrid] = useState<Grid | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [gridError, setGridError] = useState<string | null>(null)

  useEffect(() => {
    if (!open || loaded) return
    let alive = true
    api
      .detail(flip.item)
      .then((d) => {
        if (!alive) return
        setGrid(d.grid ?? null)
        setLoaded(true)
      })
      .catch((e: unknown) => {
        if (!alive) return
        setGridError(e instanceof Error ? e.message : String(e))
        setLoaded(true)
      })
    return () => {
      alive = false
    }
  }, [open, loaded, flip.item])

  const up = flip.profit >= 0
  const sellUp = (flip.instasellProfit ?? 0) >= 0
  const dumpUp = (flip.dumpProfit ?? 0) >= 0
  const orderUp = (flip.orderProfit ?? 0) >= 0
  const fee = flip.fee || 0

  return (
    <div className={`flip ${open ? 'open' : ''} ${flip.easyMoney ? 'easy' : ''}`}>
      <button
        type="button"
        className="row"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="item">
          <span className="caret" aria-hidden="true">
            ▶
          </span>
          <span className="nm">{titleise(flip.item)}</span>
          {flip.estimated ? (
            <span className="est" title="at least one material has no live listing; its market value stood in">
              est
            </span>
          ) : null}
          {flip.alternates > 0 ? (
            <span className="est" title={`${flip.alternates} other recipe(s) produce this item`}>
              +{flip.alternates}
            </span>
          ) : null}
          {flip.easyMoney ? (
            <span
              className="easy-tag"
              title={`a recorded order pays ${coinsExact(
                flip.orderUnitPrice ?? 0,
              )} each — more than the ${coinsExact(flip.cost)} of materials — and every material is listed right now`}
            >
              easy
            </span>
          ) : null}
        </span>

        <Num className="cost" value={flip.cost} format={coins} title={`materials ${coinsExact(flip.cost)}`} />
        <Num className="revenue" value={flip.revenue} format={coins} title={`sale ${coinsExact(flip.revenue)}`} />
        <Num
          className={`profit ${up ? 'up' : 'down'}`}
          value={flip.profit}
          format={coins}
          title={`profit ${coinsExact(flip.profit)}`}
        />
        <MarginRuler margin={flip.margin} />
        <Num
          className={`instasell ${
            flip.instasellProfit === null ? 'muted' : flip.instasellProfit >= 0 ? 'up' : 'down'
          }`}
          value={flip.instasellProfit}
          format={coins}
          title={
            flip.instasellProfit === null
              ? 'this item has no fixed /sell price in the table, so there is no instant payout to show'
              : `server /sell pays ${coinsExact(flip.instasellUnitPrice ?? 0)} each` +
                (flip.instasellMultiplier && flip.instasellMultiplier !== 1
                  ? ` (base ${coinsExact(flip.instasellBasePrice ?? 0)} × ${flip.instasellMultiplier}×)`
                  : '') +
                ` — ${flip.instasellSource ?? 'unattributed'}`
          }
        />
        <Confidence
          score={flip.confidence}
          label={flip.confidenceLabel}
          factors={flip.confidenceFactors}
        />
        <Num
          className={`order ${
            flip.orderProfit === null ? 'muted' : flip.orderProfit >= 0 ? 'up' : 'down'
          }`}
          value={flip.orderProfit}
          format={coins}
          title={
            flip.orderProfit === null
              ? 'no player order recorded for this item — that is unknown, not zero'
              : `someone is paying ${coinsExact(flip.orderUnitPrice ?? 0)} each` +
                (flip.orderBuyer ? ` (${flip.orderBuyer})` : '') +
                (flip.orderStale
                  ? ` — but nobody has re-checked it in over ${Math.round(
                      (flip.orderAgeSeconds ?? 0) / 3600,
                    )}h, so treat it as gone`
                  : '') +
                ` — filling ${flip.orderFillable ?? 0} craft(s) pays ${coinsExact(
                  flip.orderTotalProfit ?? 0,
                )}`
          }
        />
        <span className="listed muted num" title={flip.listedAt ?? undefined}>
          {flip.listedNow === null ? '—' : coins(flip.listedNow)}
        </span>
        <span className="age muted num">{ageFrom(flip.listedAt)}</span>
      </button>

      {open ? (
        <div className="bom">
          <div>
            <h4>Materials to buy</h4>
            <div className="mat-list">
              {flip.ingredients.map((ing) => (
                <div className="mat" key={`${ing.item}-${ing.via}`}>
                  <span className="n">
                    {titleise(ing.item)}
                    {ing.via !== 'item' && ing.via !== 'choice' ? (
                      <span className="via" title={`any ${ing.via}`}>
                        any {ing.via}
                      </span>
                    ) : null}
                    {ing.source === 'market' ? (
                      <span className="via" title="no live listing; market value used">
                        est
                      </span>
                    ) : null}
                  </span>
                  <span className="q num">{ing.count}×</span>
                  <span className="s" title={coinsExact(ing.unitPrice)}>
                    {coins(ing.subtotal)}
                  </span>
                </div>
              ))}
            </div>
            <div className="mat-total">
              <span>Materials</span>
              <span className="num">{coinsExact(flip.cost)}</span>
            </div>
          </div>

          <div>
            <h4>Grid</h4>
            {gridError ? (
              <div className="grid-note" style={{ marginTop: 0 }}>
                Could not load the grid: {gridError}
              </div>
            ) : grid ? (
              <CraftGrid grid={grid} output={flip.item} />
            ) : (
              <div className="grid-note" style={{ marginTop: 0 }}>
                Loading grid…
              </div>
            )}
          </div>

          <div>
            <h4>The arithmetic</h4>
            <div className="ledger-math">
              <div className="mline">
                <span className="k">Materials</span>
                <span className="v">{coinsExact(flip.cost)}</span>
              </div>
              <div className="mline">
                <span className="k">Buyable right now</span>
                <span className="v">
                  {flip.materialsListed} of {flip.materialsTotal} materials
                </span>
              </div>
              {fee > 0 ? (
                <div className="mline">
                  <span className="k">Auction fee</span>
                  <span className="v">{coinsExact(fee)}</span>
                </div>
              ) : null}
              <div className="mline">
                <span className="k">
                  Sells for ({flip.outputCount}× {titleise(flip.item)} at market)
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
                <span className="k">
                  Instasell — server /sell
                  {flip.instasellBasePrice !== null
                    ? ` at ${coinsExact(flip.instasellUnitPrice ?? 0)} each`
                    : ''}
                </span>
                <span className="v">
                  {flip.instasellRevenue === null
                    ? 'no fixed price for this item'
                    : coinsExact(flip.instasellRevenue)}
                </span>
              </div>
              {flip.instasellBasePrice !== null ? (
                <div className="mline">
                  <span className="k">
                    Base {coinsExact(flip.instasellBasePrice)} × {flip.instasellMultiplier ?? 1}×
                    {' '}({flip.instasellSource ?? 'unattributed'})
                  </span>
                  <span className="v">
                    {flip.instasellNote
                      ? `note: ${flip.instasellNote}`
                      : `${flip.outputCount}× sold`}
                  </span>
                </div>
              ) : null}
              <div
                className={`mline total ${
                  flip.instasellProfit === null ? '' : sellUp ? 'up' : 'down'
                }`}
              >
                <span className="k">Instasell profit</span>
                <span className="v">
                  {flip.instasellProfit === null ? '—' : coinsExact(flip.instasellProfit)}
                </span>
              </div>
              <div className="mline">
                <span className="k">
                  Sold to players (
                  {flip.dumpSales ? `${flip.dumpSales} recent sales` : 'none recorded'})
                </span>
                <span className="v">
                  {flip.dumpRevenue === null ? '—' : coinsExact(flip.dumpRevenue)}
                </span>
              </div>
              <div
                className={`mline total ${flip.dumpProfit === null ? '' : dumpUp ? 'up' : 'down'}`}
              >
                <span className="k">Profit if dumped on the market</span>
                <span className="v">
                  {flip.dumpProfit === null ? '—' : coinsExact(flip.dumpProfit)}
                </span>
              </div>
              {flip.dumpLastAt ? (
                <div className="mline">
                  <span className="k">Last recorded sale</span>
                  <span className="v">{ageFrom(flip.dumpLastAt)} ago</span>
                </div>
              ) : null}
              <div className="mline">
                <span className="k">
                  Player order
                  {flip.orderBuyer ? ` from ${flip.orderBuyer}` : ''}
                </span>
                <span className="v">
                  {flip.orderUnitPrice === null
                    ? 'none recorded for this item'
                    : `${coinsExact(flip.orderUnitPrice)} each × ${flip.orderQuantity ?? 0}`}
                </span>
              </div>
              {flip.orderUnitPrice !== null ? (
                <>
                  <div className="mline">
                    <span className="k">
                      Order age{' '}
                      {flip.orderStale
                        ? '— past the TTL, so not counted as easy money'
                        : '— still inside the TTL'}
                    </span>
                    <span className="v">{ageSeconds(flip.orderAgeSeconds)}</span>
                  </div>
                  <div className="mline">
                    <span className="k">
                      Filling the order ({flip.orderFillable ?? 0} craft
                      {(flip.orderFillable ?? 0) === 1 ? '' : 's'} of{' '}
                      {flip.outputCount})
                    </span>
                    <span className="v">{coinsExact(flip.orderTotalProfit ?? 0)}</span>
                  </div>
                  <div className="mline">
                    <span className="k">What /sell pays, once routed</span>
                    <span className="v">
                      {coinsExact(
                        Math.max(
                          ...[flip.orderUnitPrice, flip.instasellUnitPrice].filter(
                            (v): v is number => v !== null && v !== undefined,
                          ),
                          0,
                        ),
                      )}{' '}
                      each
                      {flip.orderUnitPrice !== null &&
                      (flip.instasellUnitPrice ?? 0) <= flip.orderUnitPrice
                        ? ' (the order wins)'
                        : ' (the server base wins)'}
                    </span>
                  </div>
                </>
              ) : null}
              {flip.orderNote ? (
                <div className="mline">
                  <span className="k">Order note</span>
                  <span className="v">{flip.orderNote}</span>
                </div>
              ) : null}
              <div
                className={`mline total ${
                  flip.orderProfit === null ? '' : orderUp ? 'up' : 'down'
                }`}
              >
                <span className="k">Profit per craft, filled into the order</span>
                <span className="v">
                  {flip.orderProfit === null ? '—' : coinsExact(flip.orderProfit)}
                </span>
              </div>
              <div className="mline">
                <span className="k">Confidence</span>
                <span className="v">
                  {flip.confidence}% ({flip.confidenceLabel})
                </span>
              </div>
              <div className="factors">
                {flip.confidenceFactors.map((f) => (
                  <div className="factor" key={f.key} title={f.detail}>
                    <span className="fk">{f.label}</span>
                    <span className="ftrack" aria-hidden="true">
                      <i style={{ width: `${Math.round(f.score * 100)}%` }} />
                    </span>
                    <span className="fv num">{f.contribution} pts</span>
                  </div>
                ))}
              </div>
              <div className="mline">
                <span className="k">Listed now</span>
                <span className="v">
                  {flip.listedNow === null ? 'nothing listed' : coinsExact(flip.listedNow)}
                </span>
              </div>
              <div className="bom-actions">
                <Link to={`/item/${flip.item}`}>Full breakdown →</Link>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
