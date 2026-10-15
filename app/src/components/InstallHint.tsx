import { useState } from 'react'

export const DISMISS_KEY = 'tcg-install-hint-dismissed'

export interface Platform {
  userAgent: string
  platform: string
  maxTouchPoints: number
  standalone: boolean // already opened from the home-screen icon
  secure: boolean // https (or localhost): needed for the live camera and offline use
}

export function currentPlatform(): Platform {
  const nav = navigator as Navigator & { standalone?: boolean }
  return {
    userAgent: nav.userAgent,
    platform: nav.platform,
    maxTouchPoints: nav.maxTouchPoints ?? 0,
    standalone: nav.standalone === true || window.matchMedia?.('(display-mode: standalone)').matches === true,
    secure: window.isSecureContext,
  }
}

// iPadOS reports itself as a Mac; a touch screen gives it away.
export function isIOS(p: Platform): boolean {
  return /iPhone|iPad|iPod/.test(p.userAgent) || (p.platform === 'MacIntel' && p.maxTouchPoints > 1)
}

// Chrome, Firefox and Edge on iOS mark themselves in the user agent; only Safari is sure to offer
// "Agregar a pantalla de inicio".
export function isIOSSafari(p: Platform): boolean {
  return isIOS(p) && !/CriOS|FxiOS|EdgiOS|OPiOS|GSA\//.test(p.userAgent)
}

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1'
  } catch {
    return false
  }
}

function ShareIcon() {
  return (
    <svg className="share-icon" viewBox="0 0 24 24" aria-hidden="true" width="18" height="18">
      <path d="M12 3v12M8 7l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  )
}

// iOS never offers to install a web app on its own, so the app explains how. Hidden once the app
// runs from the home screen or the employee closes the notice.
export function InstallHint({ platform = currentPlatform() }: { platform?: Platform }) {
  const [dismissed, setDismissed] = useState(readDismissed)
  if (dismissed || platform.standalone || !isIOS(platform)) return null

  const close = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1')
    } catch {
      /* private browsing: it just shows again next time */
    }
    setDismissed(true)
  }

  return (
    <aside className="banner banner-install" aria-label="Instalar la app">
      <strong>Instala la app en tu iPhone</strong>
      {isIOSSafari(platform) ? (
        <ol>
          <li>Toca <ShareIcon /> <b>Compartir</b>, abajo en Safari.</li>
          <li>Desliza y elige <b>“Agregar a pantalla de inicio”</b>.</li>
          <li>Toca <b>Agregar</b> y abre la app desde el ícono nuevo.</li>
        </ol>
      ) : (
        <p>Abre esta página en <b>Safari</b>: solo ahí aparece “Agregar a pantalla de inicio”.</p>
      )}
      {!platform.secure && (
        <p className="muted">
          Estás en una dirección sin candado (http). Usa la que empieza con <b>https</b> para tener la cámara en vivo y que
          funcione sin conexión.
        </p>
      )}
      <button className="btn btn-small" onClick={close}>Entendido</button>
    </aside>
  )
}
