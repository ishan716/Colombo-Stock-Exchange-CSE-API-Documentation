# CSE Live WebSocket API 📡

> Real-time market data push — no polling, no API key, no auth.

The CSE web portal does **not** poll the REST API for live figures. It holds a
**STOMP-over-WebSocket** connection to a Spring message broker and receives ticks
as they happen. This document covers that undocumented feed.

---

## Endpoints 🔌

| URL | Protocol | Notes |
| --- | --- | --- |
| `wss://www.cse.lk/api/ws/websocket` | Raw STOMP | ✅ **Recommended** — plain STOMP frames |
| `https://www.cse.lk/api/ws/{server}/{session}/websocket` | SockJS + STOMP | Works, but you must handle SockJS `o` / `a[...]` / `h` / `c` framing |
| `https://www.cse.lk/api/ws/info` | SockJS discovery | Returns `{"websocket":true,...}` |
| `wss://www.cse.lk/api/ws` | — | ❌ Not a direct socket (redirects) |

The official site uses the SockJS route. The raw route is far simpler to code
against and behaves identically.

**No authentication of any kind is required.** The server responds
`CONNECTED version:1.2` to an anonymous `CONNECT` frame. The SockJS info response
advertises `cookie_needed:true`, but the raw endpoint needs no cookie.

---

## Channel model 🧭

Every feed exists on **two** destinations:

| Destination | Meaning |
| --- | --- |
| `/topic/<feed>` | **Broadcast** — pushed to all clients when the market ticks |
| `/user/topic/<feed>` | **Private reply** — sent only to you, in response to a request |

You trigger a private reply by publishing an empty message to
`/app/request-<feed>`. The site's own code labels these two paths
*"Scheduled ASPI update"* vs *"Immediate ASPI data"*.

This request/reply capability is what makes the socket more useful than REST:
**one connection can replace nine REST calls**, and you can still pull a fresh
snapshot on demand at any moment.

---

## The nine feeds 📊

| Feed | `/app/request-…` | Payload |
| --- | --- | --- |
| `aspi` | `request-aspi` | ASPI value, low, high, change, percentage, sectorId, timestamp |
| `snp` | `request-snp` | S&P SL20 value, low, high, change, percentage |
| `summary` | `request-summary` | tradeVolume, shareVolume, trades, tradeDate |
| `status` | `request-status` | `{"status":"Market Closed"}` |
| `top-gainers` | `request-top-gainers` | Top 10 — symbol, price, change, % |
| `top-looses` | `request-top-looses` | Bottom 10 — symbol, price, change, % |
| `most-active-trades` | `request-most-active-trades` | Top 10 by volume + turnover |
| `today-sharePrice` | `request-today-sharePrice` | Per-symbol OHLC and last traded price |
| `daytrade` | `request-daytrade` | Day-trade list (empty `[]` when market is closed) |

---

## Minimal Python client 🐍

Requires `pip install websocket-client`. Full version:
[`examples/cse_websocket_client.py`](examples/cse_websocket_client.py).

```python
import websocket

TOPICS = ["aspi", "snp", "summary", "status", "top-gainers", "top-looses",
          "most-active-trades", "today-sharePrice", "daytrade"]
NUL = "\x00"

def stomp(cmd, headers, body=""):
    return cmd + "\n" + "".join(f"{k}:{v}\n" for k, v in headers.items()) + "\n" + body + NUL

ws = websocket.create_connection("wss://www.cse.lk/api/ws/websocket",
                                 timeout=30, origin="https://www.cse.lk",
                                 header={"User-Agent": "Mozilla/5.0"})
ws.send(stomp("CONNECT", {"accept-version": "1.2", "host": "www.cse.lk"}))
print(ws.recv().split("\n")[0])          # -> CONNECTED

for i, t in enumerate(TOPICS):
    ws.send(stomp("SUBSCRIBE", {"id": f"s{i}", "destination": f"/topic/{t}"}))
    ws.send(stomp("SUBSCRIBE", {"id": f"u{i}", "destination": f"/user/topic/{t}"}))
for t in TOPICS:
    ws.send(stomp("SEND", {"destination": f"/app/request-{t}"}))

ws.settimeout(5)
while True:
    try:
        msg = ws.recv()
    except websocket.WebSocketTimeoutException:
        continue                          # quiet when the market is closed
    if not msg.startswith("MESSAGE"):
        continue
    head, _, body = msg.partition("\n\n")
    dest = next(l[12:] for l in head.split("\n") if l.startswith("destination:"))
    print(f"{dest:34} {body.rstrip(NUL)[:90]}")
```

Sample output (market closed, snapshots returned on request):

```
CONNECTED
/user/topic/summary                {"id":36991867,"tradeVolume":1.21922439075E9,"shareVolume":50282043,...}
/user/topic/aspi                   {"id":36996242,"value":21416.61,"lowValue":21405.25,"highValue":21468.03,...}
/user/topic/snp                    {"id":36996239,"value":6028.09,"lowValue":6019.25,"highValue":6050.49,...}
/user/topic/status                 {"status":"Market Closed"}
/user/topic/daytrade               []
/user/topic/today-sharePrice       [{"id":204,"symbol":"ABAN.N0000","open":1070.0,...}]
/user/topic/most-active-trades     [{"id":57649466,"securityId":142,"symbol":"SIRA.N0000",...}]
/user/topic/top-gainers            [{"id":57648662,"securityId":246,"symbol":"SHOT.N0000",...}]
/user/topic/top-looses             [{"id":57649428,"securityId":269,"symbol":"ASPH.N0000",...}]
```

---

## Gotchas ⚠️

### 1. Timestamp formats differ between REST and WebSocket

The same logical field is serialised differently depending on transport. This
will break a parser shared between the two:

| Field | REST | WebSocket |
| --- | --- | --- |
| `todaySharePrice[].tradesTime` | `1787292473938` | `"2026-08-21T06:07:53.938+0000"` |
| `topGainers[].tradeDate` | `1787303353000` | `"2026-08-21T09:09:13.000+0000"` |
| `aspi.timestamp` | `1787304420311` | `1787304420311` *(same)* |

List endpoints switch to ISO-8601 strings over the socket; the index feeds stay
epoch milliseconds. Normalise on ingest.

### 2. The server negotiates `heart-beat:0,0`

It sends nothing at all while idle. Set a socket timeout and swallow the
timeout exception, or your client will throw on a quiet market.

### 3. Reconnect

The site's own client uses `reconnectDelay: 5000`. The connection is not
guaranteed to be long-lived — plan to reconnect and re-subscribe.

### 4. Market hours

Broadcasts on `/topic/*` only occur while the market is trading
(roughly 09:30–14:30 Sri Lanka time, Mon–Fri). Outside those hours the socket
connects and answers `/app/request-*` normally, but pushes nothing.

---

## Verification status ✅

- **Request/reply path (`/app/request-*` → `/user/topic/*`)** — fully verified.
  All nine feeds returned live data over both the raw and SockJS transports.
- **Broadcast path (`/topic/*`)** — subscriptions are accepted without error and
  the production site depends on them, but pushes were **not** directly observed
  because testing took place after market close. Confirm during trading hours.

---

## Disclaimer

Unofficial and reverse-engineered. Endpoints may change without notice. Use
responsibly — keep to one connection and do not hammer `/app/request-*`.
