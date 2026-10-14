import type { Currency } from './types'

export function money(value: number | null | undefined, currency: Currency): string {
  if (value === null || value === undefined) return '—'
  const n = value.toLocaleString('es-MX', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return currency === 'MXN' ? `$${n}` : `US$${n}`
}

// Banxico publishes the rate with 4 decimals; the customer sees the exact rate used.
export function rate(value: number): string {
  return '$' + value.toLocaleString('es-MX', { minimumFractionDigits: 4, maximumFractionDigits: 4 })
}

export const CONDITION_LABELS: Record<string, string> = {
  NM: 'Casi nueva', LP: 'Poco jugada', MP: 'Jugada', HP: 'Muy jugada', DMG: 'Dañada',
}

export const VARIANT_LABELS: Record<string, string> = {
  normal: 'Normal', holofoil: 'Holo', reverseHolofoil: 'Reverse holo',
  '1stEditionHolofoil': '1a edición holo', '1stEditionNormal': '1a edición',
  unlimitedHolofoil: 'Holo ilimitada', unlimitedNormal: 'Ilimitada',
}

export const LANGUAGE_LABELS: Record<string, string> = { en: 'Inglés', es: 'Español', ja: 'Japonés' }

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return ''
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}
