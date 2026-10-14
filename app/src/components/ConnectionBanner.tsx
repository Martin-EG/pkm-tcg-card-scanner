interface Props {
  online: boolean
  queued: number
  onRetry: () => void
}

export function ConnectionBanner({ online, queued, onRetry }: Props) {
  if (online) return null
  return (
    <div className="banner banner-offline" role="alert">
      <strong>Sin conexión con el servidor.</strong>{' '}
      Tu compra está guardada en este teléfono
      {queued > 0 ? ` y ${queued} cambio${queued === 1 ? '' : 's'} se enviará${queued === 1 ? '' : 'n'} al reconectar` : ''}.
      <button className="btn btn-small" onClick={onRetry}>Reintentar</button>
    </div>
  )
}
