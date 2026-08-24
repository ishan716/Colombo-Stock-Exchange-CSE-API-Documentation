# Colombo Stock Exchange (CSE) API 📈🏢

> **Unofficial API usage guide & Python example 🐍**  
> Explore stock market data from the Colombo Stock Exchange (CSE) via their public API endpoints — reverse-engineered since no official documentation exists. 🔍

---

<b>Visit <a href='https://gh0sth4cker.github.io/Colombo-Stock-Exchange-CSE-API-Documentation/'>this link</a> to see web view<b>

## Overview 📋

The Colombo Stock Exchange provides real-time and historical stock data via several public endpoints used by their web portal.  
This repository documents some of the known API endpoints, example responses, and Python code to fetch and parse data.

---

## API Endpoints 🔗

Base URL: `https://www.cse.lk/api/`

| Endpoint                                  | Description                                        | HTTP Method | Required Params/Data                  |
| ----------------------------------------- | -------------------------------------------------- | ----------- | ------------------------------------ |
| companyInfoSummery                        | Detailed info of a single stock/security by symbol | POST        | symbol                               |
| tradeSummary                              | Summary of trades for all securities               | POST        |                                      |
| todaySharePrice                           | Today's share price data                           | POST        |                                      |
| topGainers                                | List of top gaining stocks                         | POST        |                                      |
| topLooses                                 | List of top losing stocks                          | POST        |                                      |
| mostActiveTrades                          | Most active trades by volume                       | POST        |                                      |
| getNewListingsRelatedNoticesAnnouncements | New listings and related announcements             | POST        |                                      |
| getBuyInBoardAnnouncements                | Buy-in board announcements                         | POST        |                                      |
| approvedAnnouncement                      | Approved announcements                             | POST        |                                      |
| getCOVIDAnnouncements                     | COVID-related announcements                        | POST        |                                      |
| getFinancialAnnouncement                  | Financial announcements                            | POST        |                                      |
| circularAnnouncement                      | Circular announcements                             | POST        |                                      |
| directiveAnnouncement                     | Directive announcements                             | POST       |                                      |
| getNonComplianceAnnouncements             | Non-compliance announcements                       | POST        |                                      |
| marketStatus                              | Market open/close status                           | POST        |                                      |
| marketSummery                             | Market summary data                                | POST        |                                      |
| aspiData                                  | All Share Price Index data                         | POST        |                                      |
| snpData                                   | S&P Sri Lanka 20 Index data                        | POST        |                                      |
| chartData                                 | Intraday/historical **index** chart series         | POST        | chartId, period (`symbol` is ignored) |
| allSectors                                | Data for all sectors                               | POST        |                                      |
| detailedTrades                            | Detailed Trades                                    | POST        |                                      |
| dailyMarketSummery                        | Daily Market Summary                               | POST        |                                      |
| companyChartDataByStock                   | Per-stock OHLC chart series                        | POST        | stockId, period                      |

> All endpoints above are **POST** with `application/x-www-form-urlencoded`.
> A `GET` returns **405**, and a JSON body returns **400**.

### ⚠️ Corrections to note

**`chartData` returns index data, not stock data.** The `symbol` parameter is
**not required and is silently ignored** — passing `LOLC.N0000` or `SAMP.N0000`
returns byte-identical results. Only `chartId` + `period` matter, and `chartId`
is actually a **sectorId**:

| chartId | Series |
| --- | --- |
| `1` | ASPI (All Share Price Index) |
| `40` | S&P Sri Lanka 20 |
| `223` | Energy sector — and any other `sectorId` from `allSectors` |

`period`: `1` intraday (~298 points) · `2` week (5) · `3` month (20) · `4` quarter (60) · `5` year (240).

```bash
curl -X POST https://www.cse.lk/api/chartData -d "chartId=40&period=1"
```

**`companyChartDataByStock` — `stockId` is *not* the `securityId`** returned by
`companyInfoSummery`. It is the `id` field from `tradeSummary` / `allSecurityCode`.
For example `stockId=378` is Colombo Land (CLND), **not** LOLC — LOLC is `stockId=410`.
`period` accepts `1`–`5`; values `6` and `7` silently alias to `2`.

**Row-count limits.** `todaySharePrice`, `topGainers`, `topLooses` and
`mostActiveTrades` each return only **10 rows**, not the full market. For all
listed securities use `tradeSummary` (281 rows) or `detailedTrades` (1,319 rows).

**`getNonComplianceAnnouncements`** currently returns an empty array — the
endpoint works, there is simply no active data.

---

## Undocumented Endpoints 🕵️

Found by inspecting the CSE portal's own JavaScript bundles. These are **GET**
requests (a POST returns 405), except where noted.

| Endpoint | Method | Delivers |
| --- | --- | --- |
| `allSecurityCode` | GET | **Full ticker directory** — id, name, symbol, active flag. The lookup table for `stockId` |
| `cntSecurity` | GET | Securities with `securityId` and board info |
| `corporateAnnouncementCategory` | GET | All announcement category IDs and names |
| `smd/categories` | GET | 40+ disclosure category names |
| `events?eventType=OT&year=2026` | GET | CSE events grouped by month |
| `events/top` | GET | Featured event content |
| `news/web?top=false&type=BN` | GET | Business news archive (~1.6 MB) |
| `news/web?top=false&year=2026&type=MR` | GET | Market reviews / daily summaries |
| `news/web?top=true&type=CN&numberOfRecord=3` | GET | Latest company news |
| `notifications` | GET | Site notices |
| `banners` / `educationalVideos` / `returnAspiSnp` | GET | Site content and status flag |
| `aspi/year` | POST | Year-to-date returns for ASPI, S&P SL20 and TRI-ASPI |
| `announcementById` | POST (form: `id`) | Full announcement body by announcement ID |
| `smd` | POST (**JSON**) | Disclosure search — `{"companyIds":[...],"categories":[...]}` |

Note `smd` is the one endpoint that requires `application/json` rather than form
encoding, and both `companyIds` and `categories` must be non-empty.

Authentication endpoints (`signInNew`, `signUpSingle`, `verifyOtp`,
`forgetPassword`) and an OAuth server at `identity.cse.lk` also exist. They are
listed here for completeness only and are **not** documented or tested.

---

## Live WebSocket Feed 📡

The portal pushes real-time data over **STOMP-over-WebSocket** at
`wss://www.cse.lk/api/ws/websocket` — no API key, no auth. Nine feeds cover ASPI,
S&P SL20, market summary and status, top gainers/losers, most active trades,
today's share prices and day trades. It also supports **request/reply**, so a
single connection can replace nine REST calls.

👉 See **[WEBSOCKET.md](WEBSOCKET.md)** for the full guide and
[`examples/cse_websocket_client.py`](examples/cse_websocket_client.py) for a
working client.

---

visit <a href='https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation/blob/main/api_endpoint_urls.txt'>this link</a> to view all complete endpoint urls.

## Usage Example 💻python

### Get detailed stock info by symbol 🔍

```python
import requests

base_url = "https://www.cse.lk/api/"
endpoint = "companyInfoSummery"

data = {"symbol": "LOLC.N0000"}

response = requests.post(base_url + endpoint, data=data)

print(f"Status code: {response.status_code}")
print(response.json())  # Prints the response as a Python dictionary
```

---

## Sample Response: `companyInfoSummery` 📝

```json
{
  "reqSymbolInfo": {
    "symbol": "LOLC.N0000",
    "name": "L O L C HOLDINGS PLC",
    "lastTradedPrice": 546.5,
    "change": -2.5,
    "changePercentage": -0.455,
    "marketCap": 259696800000
  },
  "reqLogo": {
    "id": 2168,
    "path": "upload_logo/378_1601611239.jpeg"
  },
  "reqSymbolBetaInfo": {
    "betaValueSPSL": 1.0227
  }
}
```

---

## Contribution 🤝

This is an **unofficial** reverse-engineered API.  
If you discover more endpoints or useful parameters, please submit a **Pull Request**!  
Help expand the community knowledge about the Colombo Stock Exchange API. 🚀
<br>
[![Donate with PayPal](https://img.shields.io/badge/Donate-PayPal-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/donate/?hosted_button_id=FB9KXK4TEAUJ6)

---

## Disclaimer ⚠️

- Use responsibly and verify data accuracy with official CSE sources.
- API endpoints and formats may change without notice.
- This repository is for educational purposes only.

---

[![Stargazers repo roster for @GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation](https://reporoster.com/stars/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation)](https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation/stargazers)

[![Forkers repo roster for @GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation](https://reporoster.com/forks/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation)](https://github.com/GH0STH4CKER/Colombo-Stock-Exchange-CSE-API-Documentation/network/members)
