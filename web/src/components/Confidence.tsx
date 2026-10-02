import type { ConfidenceFactor } from '../api'

/** How far the inputs behind a row can be trusted, as a percentage and a bar.
 *
 *  Nothing in this ledger is a quote -- the market index cannot see the whole
 *  auction house, materials without a listing are costed from a smoothed value,
 *  and the sell side is either a fixed server price or the middle of a handful of
 *  sales. The breakdown rides in the tooltip so the score can be argued with
 *  rather than just believed. */
export default function Confidence({
  score,
  label,
  factors,
}: {
  score: number
  label: string
  factors?: ConfidenceFactor[]
}) {
  const title = factors?.length
    ? [
        `confidence ${score}% (${label})`,
        ...factors.map(
          (f) =>
            `· ${f.label} — ${Math.round(f.score * 100)}% of a ${Math.round(
              f.weight * 100,
            )}% weight (${f.contribution} pts)\n    ${f.detail}`,
        ),
      ].join('\n')
    : `confidence ${score}% (${label})`

  return (
    <span className={`conf ${label.replace(/\s+/g, '')}`} title={title}>
      <span className="bar" aria-hidden="true">
        <i style={{ width: `${Math.max(3, Math.min(100, score))}%` }} />
      </span>
      <span className="pc">{score}%</span>
    </span>
  )
}
