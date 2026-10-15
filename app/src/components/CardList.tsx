import { useState } from 'react'
import { CONDITION_LABELS, LANGUAGE_LABELS, VARIANT_LABELS, money } from '../format'
import type { CardExtras, CardPatch, Session, SessionCard, Settings } from '../types'

interface Props {
  session: Session | null
  settings: Settings | null
  extras: Record<number, CardExtras>
  onChange: (cardId: number, changes: CardPatch) => void
  onRemove: (cardId: number) => void
}

export function CardList({ session, settings, extras, onChange, onRemove }: Props) {
  if (!session || !session.cards.length) {
    return <p className="empty">Aún no hay cartas. Toma una foto en “Escanear”.</p>
  }
  return (
    <section className="cards">
      {[...session.cards].reverse().map((c) => (
        <CardRow key={c.id} card={c} extra={extras[c.id]} settings={settings}
          onChange={(ch) => onChange(c.id, ch)} onRemove={() => onRemove(c.id)} />
      ))}
    </section>
  )
}

function CardRow({ card, extra, settings, onChange, onRemove }: {
  card: SessionCard
  extra?: CardExtras
  settings: Settings | null
  onChange: (changes: CardPatch) => void
  onRemove: () => void
}) {
  const [manual, setManual] = useState('')
  const conditions = settings?.conditions.map((c) => c.code) ?? ['NM', 'LP', 'MP', 'HP', 'DMG']
  const variants = card.variants.length ? card.variants : card.variant ? [card.variant] : []
  return (
    <article className={`card ${card.accepted ? '' : 'card-rejected'}`}>
      <div className="card-images">
        {extra?.crop_url && <img src={extra.crop_url} alt="Foto" />}
        {extra?.image_url && <img src={extra.image_url} alt="Imagen oficial" />}
      </div>
      <div className="card-info">
        <h3>{card.name}</h3>
        <p>{card.set_name} · {card.number} · {LANGUAGE_LABELS[card.printed_language] ?? card.printed_language}</p>
        {extra?.warning && <p className="warn">{extra.warning}</p>}
        <Offer card={card} />
      </div>

      <div className="field">
        <span className="label">Condición</span>
        <div className="chips">
          {conditions.map((code) => (
            <button key={code} className={card.condition === code ? 'chip on' : 'chip'}
              title={CONDITION_LABELS[code]} onClick={() => onChange({ condition: code })}>{code}</button>
          ))}
        </div>
      </div>

      {variants.length > 1 && (
        <label className="field">
          <span className="label">Variante</span>
          <select value={card.variant ?? ''} onChange={(e) => onChange({ variant: e.target.value })}>
            {variants.map((v) => <option key={v} value={v}>{VARIANT_LABELS[v] ?? v}</option>)}
          </select>
        </label>
      )}

      <div className="field">
        <span className="label">Precio manual (US$)</span>
        <div className="row">
          <input inputMode="decimal" placeholder={card.price?.manual ? String(card.price.usd) : '0.00'}
            value={manual} onChange={(e) => setManual(e.target.value.replace(',', '.'))} />
          <button className="btn btn-small" disabled={!manual || Number.isNaN(Number(manual))}
            onClick={() => { onChange({ manual_price_usd: Number(manual) }); setManual('') }}>Usar</button>
          {card.price?.manual && (
            <button className="btn btn-small btn-ghost" onClick={() => onChange({ manual_price_usd: null })}>Quitar</button>
          )}
        </div>
        <a className="btn btn-secondary" href={card.ebay_url} target="_blank" rel="noreferrer">Buscar vendidos en eBay</a>
      </div>

      <label className="toggle">
        <input type="checkbox" checked={card.accepted} onChange={(e) => onChange({ accepted: e.target.checked })} />
        <span>{card.accepted ? 'El cliente la vende' : 'El cliente se la queda'}</span>
      </label>

      <button className="btn btn-remove" onClick={onRemove} aria-label={`Quitar ${card.name} de la compra`}>
        Quitar de la compra
      </button>
    </article>
  )
}

function Offer({ card }: { card: SessionCard }) {
  if (card.cash_offer === null) {
    return <p className="offer offer-none">Sin precio: búscalo en eBay y escríbelo abajo.</p>
  }
  return (
    <div className="offer">
      <p>
        Mercado {money(card.market, card.currency)}
        {card.price?.manual && <span className="tag">manual</span>}
        {card.price?.approximate && <span className="tag">aprox.</span>}
        {card.price?.stale && <span className="tag">precio de otro día</span>}
      </p>
      {card.buying === false ? (
        <p className="no-buy">No se compra (debajo del mínimo)</p>
      ) : (
        <p className="offer-values">
          <span>Efectivo <strong>{money(card.cash_offer, card.currency)}</strong></span>
          <span>Crédito <strong>{money(card.credit_offer, card.currency)}</strong></span>
        </p>
      )}
    </div>
  )
}
