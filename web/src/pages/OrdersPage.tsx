import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { type OrderEntry, type OrdersResponse, orderApi } from '../api'
import { ageSeconds, coins, coinsExact, count, titleise } from '../format'
import { Num, usePoll } from '../hooks'

/** Orders: the other half of instasell.
 *
 *  In game, /orders lists players offering to pay a price for a quantity of an
 *  item, and /sell fills one when it beats the server's own base price. So a
 *  recorded order is the best exit a craft can have -- a named buyer at a known
 *  price, with no listing to wait on.
 *
 *  No public feed carries them, so this page is where they get recorded by hand.
 *  The empty state says why rather than pretending the book is empty in-game. */
export default function OrdersPage() {
  // bumping this re-keys the poll so a write shows up immediately rather than at
  // the next interval
  const [bump, setBump] = useState(0)
  const { data, error, loading } = usePoll<OrdersResponse>(
    `/api/orders?limit=500&_=${bump}`,
    60_000,
  )

  const [item, setItem] = useState('')
  const [price, setPrice] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [buyer, setBuyer] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [easyOnly, setEasyOnly] = useState(false)
  const [craftableOnly, setCraftableOnly] = useState(true)

  const orders = data?.orders ?? []
  const book = data?.meta.book

  const shown = useMemo(() => {
    let out: OrderEntry[] = orders
    if (craftableOnly) out = out.filter((o) => o.craftable)
    if (easyOnly) out = out.filter((o) => o.easyMoney)
    return out
  }, [orders, craftableOnly, easyOnly])

  const easy = orders.filter((o) => o.easyMoney)
  const totalEasy = easy.reduce((sum, o) => sum + (o.orderTotalProfit ?? 0), 0)
  const uncraftable = orders.filter((o) => !o.craftable).length

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    setOk(null)
    const p = Number(price)
    const q = Number(quantity)
    if (!item.trim()) return setFormError('which item is the order for?')
    if (!Number.isFinite(p) || p <= 0) return setFormError('price must be a number above zero')
    if (!Number.isInteger(q) || q < 1) return setFormError('quantity must be a whole number')
    setBusy(true)
    try {
      const res = await orderApi.record({
        item: item.trim(),
        price: p,
        quantity: q,
        buyer: buyer.trim() || undefined,
        note: note.trim() || undefined,
      })
      setOk(
        res.flip?.easyMoney
          ? `recorded — and it is easy money: ${coinsExact(res.flip.orderTotalProfit ?? 0)} for ${res.flip.orderFillable} craft(s)`
          : res.flip
            ? `recorded. Materials cost ${coinsExact(res.flip.cost)}; filling it pays ${coinsExact(res.flip.orderTotalProfit ?? 0)}.`
            : 'recorded. No vanilla recipe produces this item, so there is nothing to cost against it.',
      )
      setItem('')
      setPrice('')
      setQuantity('1')
      setBuyer('')
      setNote('')
      setBump((n) => n + 1)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(name: string) {
    try {
      await orderApi.remove(name)
      setBump((n) => n + 1)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <>
      <section className="spread" aria-label="order book summary">
        <div className={easy.length > 0 ? 'easy-block' : ''}>
          <span className="k">Easy money</span>
          <span className="v accent">
            <Num value={easy.length} format={(n) => count(n)} />
          </span>
          <div className="sub">
            orders paying more than the materials cost, for an item you can buy the materials
            for right now
          </div>
        </div>
        <div>
          <span className="k">On the book</span>
          <span className="v">
            <Num value={orders.length} format={(n) => count(n)} />
          </span>
          <div className="sub">
            {count(book?.fresh ?? 0)} still inside the {book?.ttlHours ?? 0}h TTL
            {(book?.stale ?? 0) > 0 ? ` · ${count(book?.stale ?? 0)} gone stale` : ''}
          </div>
        </div>
        <div>
          <span className="k">Worth filling in total</span>
          <span className="v accent">
            <Num value={easy.length > 0 ? totalEasy : null} format={(n) => coins(n)} />
          </span>
          <div className="sub">
            {easy.length > 0
              ? 'every easy-money order filled to the last unit'
              : 'nothing on the book clears its materials cost yet'}
          </div>
        </div>
        <div>
          <span className="k">Craftable orders</span>
          <span className="v">
            <Num
              value={orders.length - uncraftable}
              format={(n) => `${count(n)} / ${count(orders.length)}`}
            />
          </span>
          <div className="sub">
            {uncraftable > 0
              ? `${count(uncraftable)} order(s) are for items with no vanilla recipe — kept, but nothing to cost`
              : 'every recorded order has a recipe to cost against'}
          </div>
        </div>
      </section>

      <form className="order-form" onSubmit={submit}>
        <div className="field grow">
          <label htmlFor="oi">Item</label>
          <input
            id="oi"
            value={item}
            onChange={(e) => setItem(e.target.value)}
            placeholder="netherite_ingot"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="op">Price each</label>
          <input
            id="op"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder="5000000"
            inputMode="numeric"
            title="what the buyer pays per item, as /orders shows it"
          />
        </div>
        <div className="field">
          <label htmlFor="oq">Quantity</label>
          <input
            id="oq"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="64"
            inputMode="numeric"
            title="how many the order wants — this is what caps how many crafts it absorbs"
          />
        </div>
        <div className="field">
          <label htmlFor="ob">Buyer</label>
          <input
            id="ob"
            value={buyer}
            onChange={(e) => setBuyer(e.target.value)}
            placeholder="optional"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div className="field">
          <label htmlFor="on">Note</label>
          <input
            id="on"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="optional"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? 'recording…' : 'record order'}
        </button>
      </form>

      {formError ? <p className="form-msg bad">{formError}</p> : null}
      {ok ? <p className="form-msg good">{ok}</p> : null}

      <div className="controls">
        <span className="count-line">
          Where to get these: in game, run <code>/orders</code> and type what it shows above.
        </span>
        <span className="spacer" />
        <label className="toggle" title="only orders for items some vanilla recipe produces">
          <input
            type="checkbox"
            checked={craftableOnly}
            onChange={(e) => setCraftableOnly(e.target.checked)}
          />
          craftable only
        </label>
        <label className="toggle easy" title="only orders that beat the materials cost">
          <input type="checkbox" checked={easyOnly} onChange={(e) => setEasyOnly(e.target.checked)} />
          easy money
        </label>
        <span className="count-line">{count(shown.length)} shown</span>
      </div>

      {error && !data ? (
        <div className="note">
          <h3>The API did not answer</h3>
          <p>{error}</p>
        </div>
      ) : null}

      {loading && !data ? (
        <>
          <div className="skeleton" />
          <div className="skeleton" />
        </>
      ) : null}

      {data && orders.length === 0 ? (
        <div className="note">
          <h3>No orders recorded yet</h3>
          <p>
            There is no public feed for DonutSMP buy orders, so craftflip cannot find them for
            you. donut.auction retired its order mirror — its <code>/orders</code> page and its
            API documentation both say so, and its search endpoint answers every query with an
            empty book. The official <code>api.donutsmp.net</code> documents 19 endpoints and
            none of them is an order endpoint. DonutStats reads the same four official
            endpoints and nothing more.
          </p>
          <p>
            What that leaves is the order book you can see yourself. Run <code>/orders</code> in
            game and record what it shows with the form above. Each one is then costed against
            live material prices, so an order that pays more than the materials cost is flagged
            as easy money and sorted to the top.
          </p>
          <p>
            Orders are written to the mounted volume, so they survive a redeploy, and expire
            after {book?.ttlHours ?? 24} hours — a buyer can fill or withdraw an offer at any
            moment, so an order nobody has re-checked is not counted as easy money.
          </p>
        </div>
      ) : null}

      {data && orders.length > 0 && shown.length === 0 ? (
        <div className="note">
          <h3>Nothing matches that filter</h3>
          <p>
            {count(orders.length)} order(s) are recorded but none match. Untick a filter to see
            them.
          </p>
        </div>
      ) : null}

      {shown.length > 0 ? (
        <div className="order-book">
          <div className="order-head">
            <span>Item</span>
            <span>Order price</span>
            <span>Wants</span>
            <span>Materials cost</span>
            <span>Profit per craft</span>
            <span>Filling it pays</span>
            <span>Crafts</span>
            <span>Age</span>
            <span />
          </div>
          {shown.map((o) => {
            const profit = o.orderProfit ?? null
            return (
              <div key={o.item} className={`order-row ${o.easyMoney ? 'easy' : ''}`}>
                <span className="item">
                  <Link to={`/item/${o.item}`}>{titleise(o.item)}</Link>
                  {o.easyMoney ? (
                    <span
                      className="easy-tag"
                      title={`${coinsExact(o.unitPrice)} each beats the ${coinsExact(o.cost ?? 0)} of materials, and every material is listed right now`}
                    >
                      easy
                    </span>
                  ) : null}
                  {o.buyer ? <span className="who">{o.buyer}</span> : null}
                </span>
                <Num value={o.unitPrice} format={coinsExact} title="what the buyer pays per item" />
                <Num value={o.quantity} format={(n) => count(n)} title="units the order wants" />
                <Num
                  value={o.cost ?? null}
                  format={coinsExact}
                  title={
                    o.craftable
                      ? `${o.materialsListed}/${o.materialsTotal} materials have a live listing`
                      : 'no recipe produces this item'
                  }
                />
                <Num
                  className={`profit ${profit === null ? 'muted' : profit >= 0 ? 'up' : 'down'}`}
                  value={profit}
                  format={coinsExact}
                />
                <Num
                  className={`profit ${
                    (o.orderTotalProfit ?? 0) === 0 ? 'muted' : (o.orderTotalProfit ?? 0) >= 0 ? 'up' : 'down'
                  }`}
                  value={o.orderTotalProfit ?? null}
                  format={coinsExact}
                  title="the order filled to its last unit"
                />
                <Num
                  value={o.orderFillable ?? null}
                  format={(n) => count(n)}
                  title={
                    o.craftablePerCraft
                      ? `${o.craftablePerCraft} per craft, so ${o.orderFillable} craft(s) fill this order`
                      : undefined
                  }
                />
                <span
                  className={`age ${o.stale ? 'stale' : 'muted'}`}
                  title={
                    o.stale
                      ? `past the ${Math.round((o.ttlSeconds ?? 0) / 3600)}h TTL — the buyer may have filled or withdrawn it`
                      : o.seenAt ?? undefined
                  }
                >
                  {ageSeconds(o.ageSeconds)}
                </span>
                <button
                  type="button"
                  className="drop"
                  onClick={() => remove(o.item)}
                  title="the buyer has taken this order down"
                >
                  forget
                </button>
              </div>
            )
          })}
        </div>
      ) : null}

      {shown.length > 0 ? (
        <p className="footnote">
          An order is a player's offer, not a promise: it can be filled or withdrawn the moment
          somebody takes it, which is why the age column matters and why a stale order is never
          counted as easy money. A row with an unlisted material is costed from market value
          rather than a live listing, and is capped in confidence for the same reason.
        </p>
      ) : null}

      {data && shown.length > 0 && data.meta.book.errors.length > 0 ? (
        <p className="form-msg bad">
          The order book had {data.meta.book.errors.length} unreadable entr(y/ies):{' '}
          {data.meta.book.errors.join('; ')}
        </p>
      ) : null}
    </>
  )
}
