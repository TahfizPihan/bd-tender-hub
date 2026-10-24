# BD Tender Hub (personal)

A self-updating tender tracker for one person. A scheduled job collects notices from e-GP, the
World Bank, private banks/NGOs and newspaper tender pages, an AI step reads the messy ones, and a
static page lets you search and filter. Every entry links back to the original notice.

```
e-GP RSS ─────────────┐
World Bank API ───────┤
bank / NGO pages ─────┼─> scraper ──> docs/tenders.json ──> docs/index.html
newspaper e-papers ───┤   (GitHub Actions, every 3h)         (private, see below)
inbox.txt (manual) ───┘   AI = Gemini free tier
```

Cost: **0** (GitHub Actions + Gemini free tier + free hosting).

## Set up (about 15 minutes)

1. Create a **private** GitHub repository and push this folder to it.
2. **Settings → Secrets and variables → Actions → New secret**: `GEMINI_API_KEY`
   (free key from https://aistudio.google.com). Needed for banks/NGOs and newspapers;
   e-GP and the World Bank work without it.
3. **Actions** tab: open *Collect tenders* and press **Run workflow**. The workflow then runs every 3 hours.
4. Pick how to view it (next section).

The workflow runs the tests first, so a broken change never overwrites your data.

## Keep it private

GitHub Pages sites are public even for private repos (except on paid plans), so don't use it. Options:

- **Simplest:** `git pull`, then `python -m http.server -d docs 8000` and open http://localhost:8000.
- **Phone and laptop:** connect the private repo to Cloudflare Pages (build output folder `docs`),
  then limit access to your own email with Cloudflare Access (Zero Trust has a free tier).

## Sources

| Source | Type | How |
|---|---|---|
| e-GP daily + weekly | Government | official RSS feeds, enabled |
| World Bank (Bangladesh) | Development partners | public JSON API; bids, EOIs and prequalification; enabled |
| BRAC e-Tender | Private / NGO | AI reads the live list page; enabled |
| Islami Bank Bangladesh | Private | AI reads the tender-notice table; enabled |
| Meghna Bank | Private | AI reads the notice board (pages 1-2); enabled |
| Uttara Bank | Private | AI reads its tender page; enabled, layout unverified |
| Newspapers (Daily Star, Prothom Alo, ...) | Newspaper | AI reads e-paper tender pages; needs setup per paper |
| `inbox.txt` | Any | you paste a page image/PDF URL |

Government agency websites are intentionally not collected: their tenders are on e-GP.

**Check the first run.** I could only read these sites through a limited tool, not from the build
sandbox, so none of the collectors has run against a live site yet. They are tested against
synthetic samples shaped like what I saw. Open the Actions log and `docs/tenders.json` after the
first run. Each source reports `ok` or an error on the page footer. Likely issues:
- *"almost no text"* means the page builds its list with JavaScript (possible for BRAC). That
  source cannot be read automatically.
- *"disallowed by robots.txt"* means the site forbids automated access; the collector respects that.
- Empty deadline/organization on e-GP items means the RSS layout needs a small parser tweak.

## How the AI page reader works

Per-site HTML scrapers break often, so for banks and NGOs the page is fetched, turned into text
with every link kept beside its row, and Gemini lists the tender notices on it. A page whose text
hasn't changed since the last run is skipped, so unchanged pages cost nothing. `MAX_PAGES_PER_RUN`
(default 30) caps AI calls per run. AI reading can be wrong: open the linked notice and confirm the
deadline before bidding.

## Adding a private company or NGO

Find the page where it lists tenders, then add to `sources.json`:

```json
{"id": "some-bank", "name": "Some Bank", "type": "ai_page", "kind": "private",
 "enabled": true, "url": "https://example.com/tender-notice"}
```

For paginated lists use `"url_template": "https://example.com/notices?page={page}", "pages": [1, 2]`.
Most private companies advertise only in newspapers and don't list tenders on their own website,
which is why the newspaper route matters.

## Newspapers

Tender ads are printed in the e-paper as page images or PDFs. The collector downloads a tender
page, asks Gemini to list every notice on it, and stores **only the extracted facts plus a link
back to the page**. The page image is not kept. Each page is read once.

- **Quick lane, `inbox.txt`:** one line per page, `direct image/PDF URL | Newspaper name`.
- **Automatic lane, `sources.json`:** for papers whose page URLs follow a pattern, set `url_template`
  with `{yyyy} {mm} {dd} {page}` and list the tender pages in `pages`, then enable it. Copy the
  `paper-template` block per paper. The URL pattern is the part to look up for each paper.

## About alltender.com

alltender.com is a paid commercial service whose terms forbid copying, reposting, reproducing or
making derivative works from its content. Using it privately doesn't change that, so this project
does not scrape it. It collects from the same kinds of original sources instead: newspapers,
company and bank websites, e-GP. Alternatives: use their free 7-day plan or a paid plan for email
alerts, or ask them about a licensed data feed.

## Rules built in

- **Duplicates** from two sources are merged when title, organization and deadline match; the
  second link is kept as "also listed". Wording often differs between sources, so some duplicates remain.
- **Retention:** tenders disappear 30 days after their deadline, or 60 days after first seen if
  they have no deadline.
- **Deadlines** are compared in Bangladesh time (UTC+6) in the browser.
- A failing source is logged and skipped; it never stops the others or wipes existing data.
- World Bank's `submission_date` is not the bid deadline, so deadlines come from the notice text.

## Not included yet

- A private Telegram bot that messages only you when a new tender matches your keywords.
- UN agencies (UNGM): its list is built by JavaScript. UNDP's site disallows automated access.

## Local use

```
pip install -r requirements.txt
python -m pytest -q tests
python -m scraper.collect --no-ai
python -m http.server -d docs 8000
```
