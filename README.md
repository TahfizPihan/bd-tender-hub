# BD Tender Hub (personal)

A self-updating tender tracker for one person. A scheduled job collects notices from e-GP, the
World Bank, private banks/NGOs and newspaper tender pages, an AI step reads the messy ones, and a
static page lets you search and filter. Every entry links back to the original notice.

```
e-GP list (browser) ──┐
BPPA notices ─────────┤
World Bank API ───────┤
bank / NGO pages ─────┼─> scraper ──> docs/tenders.json ──> docs/index.html
newspaper e-papers ───┤   (GitHub Actions, every 3h)         (private, see below)
inbox.txt (manual) ───┘   AI = Gemini free tier
```

Cost: **0** (GitHub Actions + Gemini free tier + free hosting).

## Set up (about 15 minutes)

1. Use your GitHub repository (it must be public for the web page, see below).
2. **Settings → Secrets and variables → Actions → New secret**: `GEMINI_API_KEY`
   (free key from https://aistudio.google.com). Needed for banks/NGOs and newspapers;
   e-GP and the World Bank work without it.
3. **Actions** tab: open *Collect tenders* and press **Run workflow**. The workflow then runs every 3 hours.
4. Pick how to view it (next section).

The workflow runs the tests first, so a broken change never overwrites your data.

## Update steps (do this whenever I send a new zip)

The page shows a red banner **"Your repository is still running the old collector"** when the code in
your repo is out of date. To update: unzip, open your repo on GitHub, **Add file, Upload files**, drag in
everything from the unzipped folder (including the `.github`, `scraper`, `tests` and `docs` folders and
`sources.json`, `requirements.txt`) and commit. Then **Actions, Collect tenders, Run workflow**.
Do not upload a `tenders.json` or `data` folder from the zip; your live ones stay untouched.
Check the page footer: it shows the version (for example `3.3`).

## Searching

The search box accepts `interior OR "fit-out" -road`: words are AND, `OR` or `|` means either,
quotes are an exact phrase, `-word` excludes. Chips under the tabs are saved searches (Interior and
fit-out, Furniture supply, and your own: type a search, press "+ Save this search"; they are kept in
your browser). The "Search other sites" panel opens Google, Facebook, LinkedIn and Instagram searches for
the same words. Social sites are opened by you, not scraped: their terms forbid automated copying.

bdtender.com and alltender.com terms forbid copying their content, so they are linked, not collected.
News leads (Google News RSS for interior and furniture tenders) are shown under the "News leads" tab.

## Viewing it (public repo + GitHub Pages)

1. Make the repo **public** (Settings, Danger Zone, Change visibility). It holds only public tender notices.
2. Settings, Pages: Source = *Deploy from a branch*, branch `main`, folder `/docs`.
3. Open `https://<your-user>.github.io/bd-tender-hub/`. The page loads fresh data straight from
   `raw.githubusercontent.com`, so it is current even before Pages redeploys.

## Sources

| Source | Kind | How |
|---|---|---|
| BPPA advertisements (goods, works, services) | Government | server-rendered lists plus detail pages: OTM/LTM method, funding partner (ADB, JICA, World Bank ...), closing time. New notices only after the first run |
| e-GP public tender list | Government | read with a headless browser (the list is built by JavaScript) |
| World Bank (Bangladesh) | Development partner | public JSON API |
| ADB, JICA | Development partner | headless browser plus AI; marked *experimental* |
| BRAC, Islami Bank, Meghna Bank, Uttara Bank | Private / NGO | AI reads the notice page |
| Newspapers | Private works | need one e-paper URL pattern per paper, or `inbox.txt` |

Filters on the page: method (OTM, LTM, RFQ ...), funded by (ADB, JICA, World Bank, IFC ...), category, source.
"CTM" is not a standard method in Bangladesh public procurement rules, so it is not a filter.

**Check the first run.** The e-GP and BPPA readers are tested against samples shaped like the real
pages (including a JavaScript-built mock of e-GP), not against the live sites. After the first run:
- Actions log: each source prints `[ok]` or `[fail]` with the reason.
- The page footer, "Source status": shows the same per source (experimental ones do not raise the warning banner).
- `data/egp_debug.txt` records what the browser saw on the e-GP page. If e-GP shows 0 tenders, send me that file.

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
