import { useEffect, useRef, useState } from 'react'

type Mode = 'single' | 'page'

interface Props {
  disabled: boolean
  busy: string | null
  onPhoto: (photo: Blob) => void
}

// Live camera needs HTTPS (see README). Without it, the phone's own camera app is used.
export function CameraScreen({ disabled, busy, onPhoto }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<Mode>('single')
  const [live, setLive] = useState(false)

  useEffect(() => {
    let stream: MediaStream | null = null
    if (!navigator.mediaDevices?.getUserMedia) return
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1920 }, height: { ideal: 1440 } }, audio: false })
      .then((s) => {
        stream = s
        if (videoRef.current) {
          videoRef.current.srcObject = s
          setLive(true)
        }
      })
      .catch(() => setLive(false))
    return () => stream?.getTracks().forEach((t) => t.stop())
  }, [])

  const shoot = () => {
    const video = videoRef.current
    if (!live || !video || !video.videoWidth) {
      fileRef.current?.click()
      return
    }
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    canvas.toBlob((b) => b && onPhoto(b), 'image/jpeg', 0.9)
  }

  return (
    <section className="camera">
      <div className="segmented" role="group" aria-label="Qué vas a fotografiar">
        <button className={mode === 'single' ? 'on' : ''} onClick={() => setMode('single')}>1 carta</button>
        <button className={mode === 'page' ? 'on' : ''} onClick={() => setMode('page')}>Página de 9</button>
      </div>
      <div className="viewfinder">
        <video ref={videoRef} autoPlay playsInline muted className={live ? '' : 'hidden'} />
        {!live && (
          <p className="viewfinder-hint">
            Toca el botón para abrir la cámara del teléfono.
          </p>
        )}
        <div className={`guide guide-${mode}`} aria-hidden>
          {mode === 'page' && Array.from({ length: 9 }, (_, i) => <span key={i} />)}
        </div>
      </div>
      <p className="tip">
        {mode === 'single'
          ? 'Centra la carta dentro del marco, sobre un fondo liso y con buena luz.'
          : 'Encuadra la página completa; las cartas cortadas por el borde no se cuentan.'}
      </p>
      <button className="btn btn-primary btn-shutter" onClick={shoot} disabled={disabled || !!busy}>
        {busy ?? (disabled ? 'Sin conexión' : 'Tomar foto')}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onPhoto(f)
          e.target.value = ''
        }}
      />
    </section>
  )
}
