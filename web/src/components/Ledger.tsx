import type { Flip } from '../api'
import FlipRow from './FlipRow'

export type SortKey =
  | 'profit'
  | 'margin'
  | 'cost'
  | 'revenue'
  | 'item'
  | 'profitPerUnit'
  | 'instasellProfit'
  | 'orderProfit'
  | 'orderTotalProfit'
  | 'confidence'

const COLUMNS: { key: SortKey | null; label: string; left?: boolean; title?: string }[] = [
  { key: 'item', label: 'Item', left: true },
  { key: 'cost', label: 'Cost to craft' },
  { key: 'revenue', label: 'Sells for' },
  { key: 'profit', label: 'Profit' },
  { key: 'margin', label: 'Margin' },
  { key: 'instasellProfit', label: 'Instasell', title: "what the server's /sell pays for it" },
  {
    key: 'orderProfit',
    label: 'Order',
    title: 'a recorded player buy order — someone paying this price right now',
  },
  { key: 'confidence', label: 'Conf.' },
  { key: null, label: 'Listed now' },
  { key: null, label: 'Age' },
]

export default function Ledger({
  rows,
  sort,
  onSort,
}: {
  rows: Flip[]
  sort: SortKey
  onSort: (k: SortKey) => void
}) {
  return (
    <div className="ledger">
      <div className="ledger-head">
        {COLUMNS.map((col) => (
          <span key={col.label} className={col.left ? 'l' : undefined}>
            {col.key ? (
              <button
                type="button"
                className={sort === col.key ? 'on' : ''}
                onClick={() => onSort(col.key as SortKey)}
                title={col.title ?? `sort by ${col.label.toLowerCase()}`}
              >
                {col.label}
                {sort === col.key ? ' ↓' : ''}
              </button>
            ) : (
              <span
                style={{
                  fontSize: 10,
                  letterSpacing: '0.11em',
                  textTransform: 'uppercase',
                  color: 'var(--muted)',
                }}
              >
                {col.label}
              </span>
            )}
          </span>
        ))}
      </div>

      {rows.map((flip) => (
        <FlipRow key={flip.recipeId} flip={flip} />
      ))}
    </div>
  )
}
