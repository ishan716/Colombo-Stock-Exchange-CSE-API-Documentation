"""Minimal CSE live-market client: raw STOMP over WebSocket. No SockJS, no auth."""
import json, time, websocket

TOPICS = ["aspi", "snp", "summary", "status", "top-gainers", "top-looses",
          "most-active-trades", "today-sharePrice", "daytrade"]
NUL = "\x00"

def stomp(cmd, headers, body=""):
    return cmd + "\n" + "".join(f"{k}:{v}\n" for k, v in headers.items()) + "\n" + body + NUL

ws = websocket.create_connection("wss://www.cse.lk/api/ws/websocket",
                                 timeout=30, origin="https://www.cse.lk",
                                 header={"User-Agent": "Mozilla/5.0"})
ws.send(stomp("CONNECT", {"accept-version": "1.2", "host": "www.cse.lk"}))
print(ws.recv().split("\n")[0])

for i, t in enumerate(TOPICS):                       # live broadcasts
    ws.send(stomp("SUBSCRIBE", {"id": f"s{i}", "destination": f"/topic/{t}"}))
    ws.send(stomp("SUBSCRIBE", {"id": f"u{i}", "destination": f"/user/topic/{t}"}))
for t in TOPICS:                                     # ask for a snapshot now
    ws.send(stomp("SEND", {"destination": f"/app/request-{t}"}))

ws.settimeout(5)
while True:                                          # run until Ctrl-C
    try:
        msg = ws.recv()
    except websocket.WebSocketTimeoutException:
        continue                                     # quiet when market is closed
    if not msg.startswith("MESSAGE"):
        continue
    head, _, body = msg.partition("\n\n")
    dest = next(l[12:] for l in head.split("\n") if l.startswith("destination:"))
    print(f"{dest:34} {body.rstrip(NUL)[:90]}")
