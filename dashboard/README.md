# CSE Portfolio Dashboard 📈

A personal dashboard that prices a Colombo Stock Exchange portfolio against live
market data, and surrounds it with market context — indices, sector performance,
the live leaderboards, and the price history of any listed security.

Built on the API notes in [`../README.md`](../README.md) and
[`../WEBSOCKET.md`](../WEBSOCKET.md).

## Run it

Linux, macOS, WSL, Git Bash:

```bash
./dashboard/run.sh
```

Windows PowerShell:

```powershell
.\dashboard\run.ps1
```

Either one creates `.venv` if missing, installs dependencies, starts the server
and opens <http://127.0.0.1:8000> once it answers. Ctrl-C stops it. Both run from
any directory.

| `run.sh` | `run.ps1` | Effect |
| --- | --- | --- |
| `--port N` / `-p N` | `-Port N` | Serve on a different port (default 8000) |
| `--host H` | `-BindHost H` | Bind address (default 127.0.0.1) |
| `--no-browser` / `-n` | `-NoBrowser` | Start without opening a browser |
| `--reload` / `-r` | `-Reload` | Restart on source edits |
| `--help` / `-h` | `-?` | Usage |

`run.ps1` takes `-BindHost` rather than `-Host` because `$Host` is a PowerShell
automatic variable.

If PowerShell refuses to run the script, its execution policy is blocking local
scripts:

```powershell
powershell -ExecutionPolicy Bypass -File .\dashboard\run.ps1
```

Re-running it while the dashboard is already up just opens the browser again
rather than failing on the port. If something else holds the port, it says so and
suggests the next one.

By hand instead:

```bash
pip install -r dashboard/requirements.txt
uvicorn dashboard.server.main:app --reload      # from the repo root
```

Copy the sample positions first, then edit them:

```bash
cp dashboard/holdings.sample.json dashboard/holdings.json
```

Edit positions from the **Edit holdings** button, or by hand in `holdings.json`.
That file is gitignored — your real book stays local.

## Why there is a backend

Three constraints in the CSE API decide this architecture. All were verified
against the live service.

**1. CORS is closed.** `POST /api/tradeSummary` returns `200` with no `Origin`
header, and `403` with any foreign `Origin`; the preflight carries no
`Access-Control-Allow-Origin`. A browser-only dashboard is impossible, so the
server proxies every call and the page only ever talks to its own origin.

**2. `todaySharePrice` is not the full market.** It returns 10 rows — the first
10 alphabetically — over both REST and WebSocket. It cannot price an arbitrary
portfolio. `POST /api/tradeSummary` is the only full-market price source (286
securities today; the count drifts as listings change), so portfolio valuation
polls REST while the live WebSocket feed drives the market-wide widgets.

**3. There is no security→sector mapping.** No sector field exists in
`tradeSummary`, `companyInfoSummery`, `allSecurityCode` or `cntSecurity`, and
sector-constituent endpoints 404. `/api/allSectors` gives the sector indices,
which is enough for the heatmap, but mapping *your* holdings to sectors needs the
hand-maintained table in `server/sectors.py`.

## Data sources

| Widget | Source | Transport |
| --- | --- | --- |
| Portfolio valuation | `/api/tradeSummary` | REST, 15s while open |
| Indices, market summary | `aspi`, `snp`, `summary` | WebSocket push |
| Gainers / losers / most active | those feeds | WebSocket push |
| Sector heatmap | `/api/allSectors` | REST, 60s |
| Price history, row sparklines | `/api/companyChartDataByStock` | REST, cached 15min |

One STOMP connection is held server-side and fanned out to every browser tab, per
the "keep to one connection" note in `WEBSOCKET.md`.

## Price history 🔎

Type a symbol, a bare ticker or a company name into the **Price history** card
to chart any listed security, and export the series as CSV.

The chart endpoint only accepts a numeric `stockId` — the `id` from
`tradeSummary`, *not* the `securityId` from `companyInfoSummery` — so
`server/securities.py` resolves what you typed against the live security list
first. It accepts `LOLC`, `lolc.n0000`, a stray space, or `softlogic`, and the
response names the security it actually charted.

That last part matters for companies with two share classes. `SEYB.N0000` and
`SEYB.X0000` trade at different prices, so a bare `SEYB` resolves to the voting
line and the note reports the non-voting line as an alternative rather than
charting one and staying quiet about the other.

| Period | Value | Points |
| --- | --- | --- |
| Intraday | `1` | ~300 trades |
| 1 week | `2` | 5 sessions |
| 1 month | `3` | 20 sessions |
| 1 quarter | `4` | 60 sessions |
| 1 year | `5` | 240 sessions |

`period` values `6` and `7` silently alias to `2` upstream, so they are not
offered.

**CSV export** writes exactly what is charted, so the file and the picture can
never disagree: `date,close,high,low,volume` for daily series, and
`timestamp,…` for intraday. `volume` is the series' `q` field, which matches
`tradeSummary.sharevolume` on the latest point. The `s` field is a row id rather
than a statistic and is deliberately dropped.

## What it shows that your broker screen doesn't

- **Cost weight** instead of the broker's "Holding %", which is share-count weight
  (`qty ÷ total shares`) and overstates low-priced lines — with the sample
  positions it reports RCL at 57.14% of shares against 44.84% of cost.
- **P&L against the B.E.S. price**, so you see the return after round-trip fees,
  not just against the average price.
- Day change per position, sector exposure, and your symbols badged **HELD**
  wherever they appear in the market leaderboards.
- The price history of anything listed, not only what you own.

## Gotchas handled

- WebSocket timestamps arrive as epoch ints on `/user/topic/*` replies but ISO-8601
  strings on `/topic/*` broadcasts; `ws_relay.normalise` converts both to epoch ms.
- The server negotiates `heart-beat:0,0` and is silent when idle, so the socket
  read times out and retries rather than treating silence as a failure.
- `companyChartDataByStock` wraps its series in a `{"chartData": [...]}` envelope,
  unlike `chartData` which returns a bare list.
- Daily chart timestamps are epoch ms at Colombo *local* midnight, so the page
  formats them in `Asia/Colombo` — formatting in UTC shifts every date back a day.
- Chart prices are as traded and **not** adjusted for splits: ACL.N0000's ~3:1
  split on 2025-12-29 appears in its own series as a 67% crash. The history note
  says so rather than silently smoothing it.
- `mostActiveTrades` rows have no `price` field — only `shareVolume` and `turnover`.
- Some `allSectors` rows return a null `percentage`; those tiles render greyed out.
- A holding missing from `tradeSummary` stays in the table marked *unpriced*
  rather than being silently dropped from the totals.

## Tests

```bash
pytest dashboard/tests/ -q
```

Portfolio math is pinned to hand-computed figures over the placeholder positions
in `holdings.sample.json`: cost basis 55,750.00, market value 54,895.00, P&L
−855.00 (−1.53%). The expectations were computed independently of
`server/portfolio.py`, so they check the module rather than restating its output.
Prices in the fixture are real `tradeSummary` quotes. Symbol resolution is pinned
to the voting/non-voting case. No test needs the network.

## Note

`holdings.json` is a local, gitignored file and there is no authentication. Bind
to localhost; do not deploy this as-is.
