import type { Flip } from '../api'
import FlipRow from './FlipRow'

export type SortKey = 'profit' | 'margin' | 'cost' | 'revenue' | 'item' | 'profitPerUnit'

const COLUMNS: { key: SortKey | null; label: string; left?: boolean }[] = [
  { key: 'item', label: 'Item', left: true },
  { key: 'cost', label: 'Cost to craft' },
  { key: 'revenue', label: 'Sells for' },
  { key: 'profit', label: 'Profit' },
  { key: 'margin', label: 'Margin' },
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
                title={`sort by ${col.label.toLowerCase()}`}
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
