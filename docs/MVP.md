# MVP — Pokémon Card Scanner for Buys and Trades

Oct 12, 2026 · @Martin

## Summary

A web app for the counter's phone that identifies Pokémon cards from a photo, looks up their market price, and calculates the cash and store-credit offer. It is not this week's challenge submission; it's the second project, to be tested in a couple of shops in Mexicali.

**Who it's for:** small TCG shops that buy collections and take cards in trade, in English, with Spanish and Japanese cards as optional languages the shop can turn on or off.

**The problem:**

- Going through a collection of hundreds of cards takes a long time: identify each one, look up its price on TCGplayer or eBay, convert to pesos, and apply the percentage.
- Condition changes the price and is judged by eye, differently depending on who's at the counter.
- Japanese and Spanish cards are harder to look up than English ones.

**The promise:** an offer broken down card by card in a fraction of today's time, with the same pricing rules for every employee.

## Business rules

The offer comes from one formula: market price in dollars, optionally converted to pesos at the day's exchange rate, adjusted for condition, and multiplied by 85% for cash or 90% for credit.

```latex
\text{Offer} = \text{Price}_{USD} \times \text{FX}_{day} \times \text{Factor}_{condition} \times \begin{cases} 0.85 & \text{cash} \\ 0.90 & \text{credit / trade} \end{cases}
```

**Market price**

| Case | Primary source | Fallback |
| --- | --- | --- |
| English card | TCGplayer market price | Recent eBay sales |
| Japanese card | Recent eBay sales | Manual entry by the employee |
| Spanish card | Recent eBay sales | English version's price, marked as approximate |

**Condition:** the employee picks the condition with one tap. Each condition has a factor set by the shop; the values live in config.

| Condition | Factor |
| --- | --- |
| Near Mint (NM) | To be set with the shop |
| Lightly Played (LP) | To be set with the shop |
| Moderately Played (MP) | To be set with the shop |
| Heavily Played (HP) | To be set with the shop |
| Damaged (DMG) | To be set with the shop |

**Exchange rate:** optional, with a USD → MXN toggle. When it's on, the rate is taken once a day from an official source and shown on screen with its date, so the customer can see it. When it's off, the exchange rate is left out and prices and offers are shown in US dollars.

**Example (illustrative values):** an NM card worth US$10, exchange rate $18.50, and NM factor 1.0. Market = $185.00; cash offer = $157.25; credit offer = $166.50. With conversion off: cash offer = US$8.50; credit offer = US$9.00.

**Shop settings (toggles)**

| Setting | Default | When on | When off |
| --- | --- | --- | --- |
| Spanish cards | Off | Spanish catalog is indexed and searched; prices from eBay or manual entry | Only English cards are identified |
| Japanese cards | Off | Japanese catalog is indexed and searched; prices from eBay or manual entry | Japanese cards aren't identified; the employee can still add one manually |
| USD → MXN conversion | On | Prices and offers in pesos at the day's Banxico rate | Prices, offers, and the minimum buy price in US dollars |

English cards are always on. For now the toggles are environment variables on the server (ENABLE\_SPANISH, ENABLE\_JAPANESE, CONVERT\_TO\_MXN) with these defaults; a settings screen may come later.

## Counter flow

The employee takes the photo, confirms, and adjusts condition; the system handles lookup, conversion, and math.

1. **New buy.** The employee opens the app on the phone and starts a session for the customer.
2. **Photo.** They photograph one card, or several on a plain background. The app crops each card and straightens the image.
3. **Identification.** The system proposes the card (name, set, number, language) with its official image next to the photo.
   - If confidence is high, it's accepted.
   - If it's low, it shows the 3 most likely options to pick with a tap.
4. **Condition and variant.** NM by default; the employee changes it if needed and marks holo, reverse holo, or first edition when the system can't tell.
5. **Price.** The market price is looked up, converted to pesos if conversion is on, and the cash and credit offers are shown. Cards below a configurable minimum are marked "not buying".
6. **Customer summary.** A list with thumbnail, condition, market price, and offer, plus the cash and credit totals and the exchange rate used.
7. **Close.** The cards the customer agreed to sell are marked and the list is exported to CSV for inventory.

## Scope

The MVP buys single Pokémon cards from phone photos; automatic condition grading and full inventory come later.

| In the MVP | Out of the MVP |
| --- | --- |
| Pokémon in English; Spanish and Japanese as optional toggles | Magic, Yu-Gi-Oh, One Piece, and other games |
| Phone camera photo, one or several cards | Fixed webcam or flatbed scanner |
| Condition picked by the employee | Automatic condition detection with a vision model |
| TCGplayer and eBay prices, with optional USD → MXN conversion | Price history and alerts |
| Cash and credit offer, minimum buy price | Sales, point of sale, payments |
| Export the buy to CSV | Full inventory and sync with another system |
| Single cards | Sealed product, graded cards (PSA, CGC) |

## Card identification and data sources

Identification is done with open models and an open catalog; English prices and the exchange rate have free APIs, but eBay sales don't, so in the MVP eBay is a link plus manual entry.

**How a card is identified**

1. **Crop:** OpenCV detects each card's outline in the photo and corrects perspective.
2. **Visual match:** an open image embedding model (CLIP, SigLIP, or DINOv2) turns the card into a vector and finds the closest matches in a local index of official images of every card.
3. **Text confirmation:** open OCR (PaddleOCR) reads the collector number and set code at the bottom to break ties between reprints and variants that share artwork.
4. **Language:** decided from the text read (Japanese script, Spanish words) and from which version of the index matches. Only languages enabled in settings are loaded and searched, which also keeps searches faster.

**Data sources**

| Need | Source | Notes |
| --- | --- | --- |
| Catalog and images in English, Spanish, and Japanese | [TCGdex](https://tcgdex.dev/) | Open and free, with a Python SDK; completeness varies by language ([status](https://tcgdex.dev/status)) |
| TCGplayer market price (English) | [Pokémon TCG API (pokemontcg.io)](https://pokemontcg.io) | Includes TCGplayer market price in USD; free key |
| Recent eBay sales | [Marketplace Insights API](https://developer.ebay.com/api-docs/buy/marketplace-insights/static/overview.html) | Limited release, requires eBay approval; in the MVP the sold-items search opens and the employee enters the price |
| Japanese card prices | [pokemontcgapi.com](https://mcpservers.org/servers/pokemontcgapi/mcp-server) | Unofficial; covers Japanese print runs and states each price's source. Evaluate before depending on it |
| Day's exchange rate | [Banxico SIE, series SF43718 (FIX)](https://rdrr.io/cran/bbk/man/banxico_data.html) | Official, free token; published on business days |

**Biggest technical risk:** Japanese cards, due to an incomplete catalog and hard-to-get prices. That's why Japanese is off by default: a shop turns it on when it's ready, and the MVP still allows entering the price manually.

## Architecture and stack

The phone only takes the photo; all the heavy work runs on a shop computer on the same Wi-Fi network.

| Component | Technology | What it does |
| --- | --- | --- |
| Counter app | React as an installable web app (PWA) | Camera, card confirmation, condition, customer summary |
| Server | FastAPI on the shop computer | Receives photos, identifies, calculates offers, and stores buys |
| Crop | OpenCV | Detects and straightens each card in the photo |
| Visual identification | Open embedding model (CLIP/SigLIP/DINOv2) + FAISS index | Finds the closest cards across the whole catalog |
| Text reading | PaddleOCR | Reads collector number, set, and language |
| Prices | pokemontcg.io client + daily cache | Avoids repeating lookups for the same card in a day |
| Exchange rate | Banxico SIE client | One query per day, only when conversion is on |
| Data | SQLite | Buys, cards, prices used, employee corrections |
| Export | CSV | Input to the shop's inventory |

**Index preparation:** done once on your computer (download images from TCGdex and compute their vectors) and copied to the shop. Updated when a new set comes out.

**Hardware:** embeddings and OCR are lightweight and should run on CPU in a few seconds per card at most; this needs to be measured in Phase 1. Still need to confirm what equipment each shop has.

**Settings:** environment variables on the server turn Spanish cards, Japanese cards, and USD → MXN conversion on or off, until a settings screen is built. Business rules stay in `config/reglas.yaml`, so every phone at the counter uses the same settings.

## Why open

A shop can scan thousands of cards a month and needs the scanner to work at an event without internet; local open models solve both.

- **Cost at volume:** with a paid vision API, every scanned card costs money. A 500-card collection is 500 calls. Locally, the cost is zero.
- **No internet needed:** identification and offers work with the local index; only the price needs a connection, and it's cached for tournaments and fairs.
- **Tunable to the niche:** the index includes the Spanish and Japanese editions these shops buy, and employee corrections help improve matching.
- **Open catalog:** TCGdex is open code and open data, so the product doesn't depend on a card recognition vendor keeping its price or its service.
- **No photos sent to third parties:** photos of customers' collections stay in the shop.

## Metrics, shop test, and open questions

The test is in one of the shops you know, with a real collection valued twice: by hand and with the scanner.

| Metric | How it's measured | MVP target |
| --- | --- | --- |
| Time to value a collection | Minutes per 100 cards, by hand vs. scanner | At least 3× faster |
| English identification accuracy | Cards correct on the first try ÷ total | 90% or more |
| Spanish and Japanese accuracy | Same, per language (only if enabled) | Measure; no target |
| Offer difference | Scanner offer vs. manual offer | Report in pesos and % |
| Willingness to pay | Direct question to the owner after the test | Monthly price they mention |

**Open questions for the shops**

- [ ] Price factor for each condition (NM, LP, MP, HP, DMG)
- [ ] Do the 85% and 90% apply to the TCGplayer market price, or to another value?
- [ ] Minimum per card to buy it, and what to do with common cards (bought in bulk?)
- [ ] How do they track inventory today, and which columns would they need in the CSV?
- [ ] What computer do they have at the counter?
- [ ] Which exchange rate exactly: Banxico FIX, their bank's, or an exchange house's?
