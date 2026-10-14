import { LANGUAGE_LABELS } from '../format'
import type { Candidate, PendingReview } from '../types'

interface Props {
  reviews: PendingReview[]
  onPick: (review: PendingReview, chosen: Candidate | null) => void
}

export function ReviewList({ reviews, onPick }: Props) {
  if (!reviews.length) return null
  return (
    <section className="reviews">
      <h2>Confirma {reviews.length === 1 ? 'esta carta' : `estas ${reviews.length} cartas`}</h2>
      {reviews.map((r) => (
        <article key={r.key} className="review">
          <div className="review-photo">
            <img src={r.card.crop_url} alt="Foto de la carta" />
            {r.card.warning && <p className="warn">{r.card.warning}</p>}
          </div>
          <p className="review-question">¿Cuál es?</p>
          <div className="options">
            {r.card.candidates.map((c) => (
              <button key={`${c.language}-${c.id}`} className="option" onClick={() => onPick(r, c)}>
                <img src={c.image_url} alt="" />
                <span className="option-text">
                  <strong>{c.name}</strong>
                  <span>{c.set_name} · {c.number}</span>
                  <span className="muted">{LANGUAGE_LABELS[c.language] ?? c.language} · {Math.round(c.confidence * 100)}%</span>
                </span>
              </button>
            ))}
          </div>
          <button className="btn btn-ghost" onClick={() => onPick(r, null)}>Ninguna, descartar</button>
        </article>
      ))}
    </section>
  )
}
