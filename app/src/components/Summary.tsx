import { CONDITION_LABELS, money, rate, shortDate } from '../format'
import type { CardExtras, Session, Settings } from '../types'

interface Props {
  session: Session | null
  settings: Settings | null
  extras: Record<number, CardExtras>
  onExport: () => void
  onNew: () => void
}

function sourceLabel(p: Session['cards'][number]['price']): string {
  if (!p) return 'sin precio'
  if (p.manual) return 'precio manual'
  const base = p.source === 'tcgplayer' ? 'TCGplayer' : p.source
  return p.approximate ? `${base} (aprox., versión en inglés)` : base
}

// Shown to the customer: large text, totals first, currency and exchange rate always visible.
export function Summary({ session, settings, extras, onExport, onNew }: Props) {
  const currency = session?.currency ?? settings?.currency ?? 'MXN'
  const convert = session ? session.fx !== null : settings?.convert_to_mxn ?? true
  return (
    <section className="summary">
      <p className="currency-note" data-testid="currency">
        {currency === 'MXN' ? 'Precios en pesos mexicanos (MXN)' : 'Precios en dólares (USD)'}
      </p>
      {convert && session?.fx && (
        <p className="fx" data-testid="fx">
          Tipo de cambio: {rate(session.fx.rate)} por dólar · Banxico, {shortDate(session.fx.date)}
          {session.fx.stale && ' (último disponible)'}
        </p>
      )}

      {!session || !session.cards.length ? (
        <p className="empty">Todavía no hay cartas en esta compra.</p>
      ) : (
        <>
          <div className="totals">
            <div><span>Efectivo</span><strong data-testid="total-cash">{money(session.totals.cash, currency)}</strong></div>
            <div><span>Crédito en tienda</span><strong data-testid="total-credit">{money(session.totals.credit, currency)}</strong></div>
          </div>
          <p className="muted">
            {session.totals.cards_buying} carta{session.totals.cards_buying === 1 ? '' : 's'} en la oferta
            {session.totals.cards_not_buying > 0 && ` · ${session.totals.cards_not_buying} no se compran`}
            {session.totals.cards_without_price > 0 && ` · ${session.totals.cards_without_price} sin precio`}
          </p>
          <ul className="summary-list">
            {session.cards.map((c) => (
              <li key={c.id} className={c.accepted ? '' : 'rejected'}>
                {extras[c.id]?.image_url && <img src={extras[c.id].image_url} alt="" />}
                <div>
                  <strong>{c.name}</strong>
                  <span>{CONDITION_LABELS[c.condition] ?? c.condition} · {sourceLabel(c.price)}</span>
                  <span>Precio de mercado: {money(c.market, c.currency)}</span>
                </div>
                <div className="summary-offer">
                  {!c.accepted ? <span>Se la queda</span>
                    : c.buying === false ? <span>No se compra</span>
                    : c.cash_offer === null ? <span>Sin precio</span>
                    : <>
                        <span>{money(c.cash_offer, c.currency)}</span>
                        <span className="muted">crédito {money(c.credit_offer, c.currency)}</span>
                      </>}
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="summary-actions">
        <button className="btn btn-secondary" onClick={onExport} disabled={!session?.cards.length}>Exportar CSV</button>
        <button className="btn btn-ghost" onClick={onNew}>Nueva compra</button>
      </div>
    </section>
  )
}
