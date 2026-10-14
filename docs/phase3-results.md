# Phase 3 — Counter app: results

Oct 14, 2026

## Verdict

The counter app is built and both [AUTO] gate items pass. It's a React + Vite PWA in Mexican Spanish, served by the shop server, and it handles the whole flow: photo → confirm the card → condition and price → customer summary → CSV.

I ran it end to end against the real server at phone size (375 px wide). That run covered identifying a card, the live Banxico rate, a condition change, the summary, and losing and regaining the server. The three [MANUAL] items need a real phone and a real person, so they're yours.

## QA gate

| item | result | evidence |
|---|---|---|
| [MANUAL] A card is added in under 10 s from photo to offer | **NEEDS MANUAL CHECK** | Server side, a single-card photo takes 1–2 s to identify plus about 0.1 s to price (Phases 1–2). The very first `/identify` after starting the server took 6.2 s, including loading the OCR models (measured with curl). I didn't time the browser test. Measure it on a real phone over the shop Wi-Fi |
| [MANUAL] Usable one-handed, comfortable buttons | **NEEDS MANUAL CHECK** | Every control is at least 48 px tall and the main ones 56–72 px. The three tabs and the shutter button sit at the bottom of the screen |
| [MANUAL] Someone outside the shop understands the summary | **NEEDS MANUAL CHECK** | The summary leads with the currency, then the exchange rate with its source and date, then large totals. Each card shows condition, price source, market price and offer |
| [AUTO] When the server connection drops, the app shows a notice and keeps the session | **PASS** | `app/src/test/offline.test.tsx` (2 tests). Also checked live, details below |
| [AUTO] The summary shows the active currency and hides the exchange rate when conversion is off | **PASS** | `app/src/test/summary.test.tsx`: in pesos it shows "Precios en pesos mexicanos (MXN)" and "Tipo de cambio: $18.4888 por dólar · Banxico, 14/10/2026"; in dollars it shows "Precios en dólares (USD)" with no exchange rate |

Tests: app 8 (`cd app && npm test`), server 154 (`python -m pytest -q`).

The live connection-loss check, step by step:
1. Stopped the server.
2. Changed a card to MP. The notice appeared ("Sin conexión con el servidor. Tu compra está guardada en este teléfono y 1 cambio se enviará al reconectar") and the change was queued on the phone.
3. Reloaded the page with the server still down. The app came back from its offline cache, with the session and the queued change.
4. Restarted the server. The notice went away, the queue emptied, and the server had the card at MP with the offer recalculated ($148.29 = 249.23 × 0.70 × 0.85).

### [MANUAL] for the owner

1. **Set up one phone:**
   - Run `python scripts/make_cert.py` on the shop PC.
   - Start uvicorn with HTTPS.
   - Install the certificate on the phone and add the app to the home screen.

   The steps are in the README under "Set up each phone". Check that the live camera and the guide frame appear.
2. **Time 5–10 cards** from shutter to offer. Each should take under 10 s.
3. **Use it one-handed** for a whole buy.
4. **Show the "Resumen" screen** to someone outside the shop and see whether they understand it without help.

## What was built

- **`app/`: React 19 + Vite 6 + TypeScript.**
  - Installable PWA: manifest, icons and a service worker that caches only the app itself. Prices and offers always come from the server.
  - FastAPI serves the built app, so the phone opens the shop PC's address and nothing else needs configuring.
- **Escanear:**
  - Live rear camera with a guide frame, for 1 card or a 3×3 binder page.
  - Without HTTPS or camera permission, it falls back to the phone's own camera app.
  - The photo goes to `/identify`. The shutter is disabled while offline.
- **Cartas:**
  - Confident matches are added to the session automatically.
  - Low-confidence cards (`needs_review`, which includes Spanish/Japanese flags and catalog gaps) show the 3 options with images, or "Ninguna, descartar". Picking an option other than the first also sends a `/corrections` entry.
  - Each card shows its crop next to the official image, plus name, set, number and language, and any language warning.
  - Per card: condition chips (NM default), variant (when more than one has a price), "Buscar vendidos en eBay", a manual price field in USD (with "Quitar"), and accepted ("El cliente la vende / se la queda").
- **Resumen:**
  - The currency, plus the exchange rate with its source and date when converting to pesos.
  - Cash and credit totals, and each card's condition, price source (TCGplayer / precio manual / aprox.) and offer.
  - Cards marked "No se compra", "Sin precio" or "Se la queda".
  - "Exportar CSV" and "Nueva compra".
- **CSV:** columns `id, name, set, number, language, variant, condition, price_usd, source, exchange_rate, cash_offer, credit_offer, accepted`. The file is UTF-8 with a BOM so Excel opens it correctly.
- **Lost connection:**
  - The whole state (settings, session, crops, pending reviews, queued changes) is saved on the phone after every change.
  - A failed request switches to offline mode: the notice appears, the server is checked every 5 s, and queued changes are sent in order once it's back.
- **Server changes:**
  - `/identify` now returns `confidence` clipped to 0–1, plus the raw `score`.
  - New `/certificado` route.
  - The built app is mounted at `/`.
- **`scripts/make_cert.py`:**
  - A shop certificate authority (ECDSA P-256, 10 years, made once) and a server certificate for `localhost`, the hostname, the LAN IP and any `--host`.
  - The server certificate lasts 825 days, the most iOS accepts.
  - Re-running keeps the authority, so phones don't need anything reinstalled.
  - Checked live: HTTPS answers with the shop authority and is rejected without it.

## Known limits

- **Installing the certificate on a phone takes manual steps** in its settings (about 5 minutes per phone). I didn't install it anywhere, because that changes a device's security trust settings.
- **No new photos while offline.** Identification runs on the server, so the shutter is disabled until it's back. Changes to cards already added are queued.
- **The project folder is on the iCloud-synced Desktop.** Every git branch switch makes iCloud create ` 2` duplicate files; this happened twice during this work. Move the project to a folder outside iCloud, such as `~/Developer`, or turn off Desktop sync. `data/` is already excluded via `data.nosync`.

## Next

Phase 4: install on the shop PC and test with a real collection (see `docs/sequence-builder.md`).
