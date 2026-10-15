import { useEffect } from 'react'
import type { RemovedCard } from '../types'

export const UNDO_MS = 6000

interface Props {
  removed: RemovedCard | null
  onUndo: () => void
  onTimeout: () => void
}

// After a card is removed, offers "Deshacer" for a few seconds instead of asking first.
export function UndoToast({ removed, onUndo, onTimeout }: Props) {
  useEffect(() => {
    if (!removed) return
    const t = setTimeout(onTimeout, UNDO_MS)
    return () => clearTimeout(t)
  }, [removed, onTimeout])

  if (!removed) return null
  return (
    <div className="toast" role="status">
      <span>Quitaste <strong>{removed.card.name}</strong></span>
      <button className="btn btn-small btn-undo" onClick={onUndo}>Deshacer</button>
    </div>
  )
}
