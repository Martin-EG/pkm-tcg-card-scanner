# TCG Buylist Scanner

Project: Pokémon card scanner for small TCG shops in Mexicali, Mexico. The employee photographs cards with a phone; the system identifies them, looks up their price, and calculates the buy offer in cash and in store credit.

Constraints:
- The server runs on a shop PC, probably with no GPU. The phone only takes photos and shows results over the local Wi-Fi network.
- Identification is 100% local with open models: image embeddings (CLIP/SigLIP/DINOv2) + FAISS index + PaddleOCR. Customer photos never leave the shop.
- Catalog and reference images: TCGdex. English is always on; Spanish and Japanese are optional languages toggled with environment variables.
- Prices: pokemontcg.io (TCGplayer market price, USD). eBay sold items: no API; open the search and enter manually. Exchange rate: Banxico SIE series SF43718, used only when CONVERT_TO_MXN is true.
- All business rules live in config/reglas.yaml. No hardcoded values.
- Stack: Python 3.11+, FastAPI, OpenCV, FAISS, PaddleOCR, SQLite; React + Vite as a PWA.
- Code and comments in English; UI in Mexican Spanish.
- pytest tests.

Offer rules:
- offer = price_usd * (exchange_rate if CONVERT_TO_MXN else 1) * condition_factor * (0.85 cash | 0.90 credit)
- Conditions: NM, LP, MP, HP, DMG; factors to be set with the shop (configurable).
- Configurable minimum buy price per card.
- Settings come from environment variables (.env), read once at startup with a typed loader; changing one means editing .env and restarting the server. No settings screen yet. Defaults: ENABLE_SPANISH=false, ENABLE_JAPANESE=false, CONVERT_TO_MXN=true. When CONVERT_TO_MXN is false, prices, offers, and the minimum are in USD.
- Every offer stores the price, source, date, and exchange rate used. A manually entered price is marked as manual.

How to work:
- Propose a short plan before writing code and wait for my OK.
- Small steps, tests at the end of each step.
- If something isn't defined here, ask.
- Every phase prompt ends with a QA gate. Check every item, report PASS / FAIL / NEEDS MANUAL CHECK with evidence, and never call a phase done while any item fails. [AUTO] items you verify yourself; [MANUAL] items are for me, so list them for me to confirm.
