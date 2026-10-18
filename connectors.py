"""Broker connectors (read-only holdings). Zerodha Kite flow; verify endpoints against current Kite Connect docs."""
import os, json, hashlib, urllib.request, urllib.parse

def _req(url, data=None, headers=None):
    r = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, headers=headers or {})
    with urllib.request.urlopen(r, timeout=20) as f: return json.load(f)

def kite_login_url():
    k = os.getenv("KITE_API_KEY")
    if not k: raise RuntimeError("KITE_API_KEY is not set")
    return f"https://kite.zerodha.com/connect/login?v=3&api_key={k}"      # set the app's redirect URL to your frontend

def kite_holdings(request_token):
    k, sec = os.getenv("KITE_API_KEY"), os.getenv("KITE_API_SECRET"); hdr = {"X-Kite-Version": "3"}
    chk = hashlib.sha256((k + request_token + sec).encode()).hexdigest()
    tok = _req("https://api.kite.trade/session/token", {"api_key": k, "request_token": request_token, "checksum": chk}, hdr)["data"]["access_token"]
    held = _req("https://api.kite.trade/portfolio/holdings", headers={**hdr, "Authorization": f"token {k}:{tok}"})["data"]
    rows = []
    for x in held:
        val = ((x.get("quantity") or 0) + (x.get("t1_quantity") or 0)) * (x.get("last_price") or 0)
        if val > 0: rows.append(dict(symbol=x["tradingsymbol"], name=x["tradingsymbol"], cls="Equity", ccy="INR", sector="Unclassified", region="IN",
                                     value=val, yf=x["tradingsymbol"] + (".BO" if x.get("exchange") == "BSE" else ".NS"), dur=0))
    return rows
