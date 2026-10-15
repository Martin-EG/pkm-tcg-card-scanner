import { useState } from 'react'
import { CameraScreen } from './components/CameraScreen'
import { CardList } from './components/CardList'
import { ConnectionBanner } from './components/ConnectionBanner'
import { InstallHint } from './components/InstallHint'
import { ReviewList } from './components/ReviewList'
import { Summary } from './components/Summary'
import { UndoToast } from './components/UndoToast'
import { downloadCsv } from './csv'
import { useCounter } from './store'

type Tab = 'scan' | 'cards' | 'summary'

export default function App() {
  const counter = useCounter()
  const { state, online, busy, message } = counter
  const [tab, setTab] = useState<Tab>('scan')
  const cardCount = state.session?.cards.length ?? 0
  const currency = state.session?.currency ?? state.settings?.currency

  return (
    <div className={state.undo ? 'app app-with-toast' : 'app'}>
      <header className="top">
        <h1>Compra{state.session ? ` #${state.session.id}` : ''}</h1>
        {currency && <span className="badge">{currency}</span>}
      </header>
      <ConnectionBanner online={online} queued={state.queue.length} onRetry={counter.retry} />
      <InstallHint />
      {message && (
        <div className="banner banner-error" role="alert">
          {message} <button className="btn btn-small" onClick={counter.dismissMessage}>OK</button>
        </div>
      )}

      <main>
        {tab === 'scan' && (
          <>
            <CameraScreen disabled={!online} busy={busy} onPhoto={async (photo) => {
              const res = await counter.scan(photo)
              if (res) setTab('cards')
            }} />
          </>
        )}
        {tab === 'cards' && (
          <>
            <ReviewList reviews={state.reviews} onPick={counter.resolveReview} />
            <CardList session={state.session} settings={state.settings} extras={state.extras}
              onChange={counter.changeCard} onRemove={counter.removeCard} />
          </>
        )}
        {tab === 'summary' && (
          <Summary session={state.session} settings={state.settings} extras={state.extras}
            onExport={() => state.session && downloadCsv(state.session)}
            onNew={() => {
              if (!state.session || confirm('¿Empezar una compra nueva? La actual queda guardada en el servidor.')) {
                counter.newSession()
                setTab('scan')
              }
            }} />
        )}
      </main>

      <UndoToast removed={state.undo} onUndo={counter.undoRemove} onTimeout={counter.clearUndo} />

      <nav className="tabs">
        <button className={tab === 'scan' ? 'on' : ''} onClick={() => setTab('scan')}>Escanear</button>
        <button className={tab === 'cards' ? 'on' : ''} onClick={() => setTab('cards')}>
          Cartas{cardCount + state.reviews.length > 0 && <span className="count">{cardCount + state.reviews.length}</span>}
        </button>
        <button className={tab === 'summary' ? 'on' : ''} onClick={() => setTab('summary')}>Resumen</button>
      </nav>
    </div>
  )
}
