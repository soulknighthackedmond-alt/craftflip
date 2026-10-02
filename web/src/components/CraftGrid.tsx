import type { Grid } from '../api'
import { coins } from '../format'
import { titleise } from '../format'

/** The recipe's real craft grid, each cell showing what goes in it and what that
 *  material costs. Tagged slots are marked, since the price shown is whichever
 *  member of the tag is cheapest to buy. */
export default function CraftGrid({ grid, output }: { grid: Grid; output: string }) {
  if (!grid.cells) {
    const slots = grid.slots ?? []
    return (
      <div>
        <div className="slot-tray">
          {slots.map((slot, i) => (
            <div
              key={`${slot.item}-${i}`}
              className={`cell ${slot.tag ? 'tagged' : ''}`}
              title={
                slot.item
                  ? `${titleise(slot.item)} — ${coins(slot.unitPrice)} each, ${slot.count} needed`
                  : 'unpriced slot'
              }
            >
              <span className="cn">
                {slot.item ? titleise(slot.item) : '—'}
                {slot.count > 1 ? ` ×${slot.count}` : ''}
              </span>
              <span className="cp">{coins(slot.unitPrice)}</span>
            </div>
          ))}
        </div>
        <div className="grid-note">
          Shapeless recipe — the arrangement does not matter, only the materials.
          Output: {titleise(output)}.
        </div>
      </div>
    )
  }

  const size = grid.size ?? 3

  return (
    <div>
      <div
        className="grid3"
        style={{
          gridTemplateColumns: `repeat(${size}, 62px)`,
          gridTemplateRows: `repeat(${size}, 62px)`,
        }}
      >
        {grid.cells.map((row, r) =>
          row.map((cell, c) => (
            <div
              key={`${r}-${c}`}
              className={`cell ${cell?.item ? '' : 'empty'} ${cell?.tag ? 'tagged' : ''}`}
              title={
                cell?.item
                  ? `${titleise(cell.item)} — ${coins(cell.unitPrice)} each`
                  : 'empty slot'
              }
            >
              {cell?.item ? (
                <>
                  <span className="cn">{titleise(cell.item)}</span>
                  <span className="cp">{coins(cell.unitPrice)}</span>
                </>
              ) : null}
            </div>
          )),
        )}
      </div>
      <div className="grid-note">
        Grid costs the cheapest member of each tagged slot. Output: {titleise(output)}.
      </div>
    </div>
  )
}
