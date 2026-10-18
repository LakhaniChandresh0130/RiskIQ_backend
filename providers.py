"""Reference-data providers. USD/INR spot from Frankfurter (ECB data); falls back to USDINR_SPOT env. Verify the URL against current docs."""
import os, json, time, urllib.request
_c = (0, 0.0)
def usdinr():
    global _c
    if time.time() - _c[0] < 3600 and _c[1]: return _c[1]
    try:
        with urllib.request.urlopen("https://api.frankfurter.dev/v1/latest?base=USD&symbols=INR", timeout=5) as f: _c = (time.time(), float(json.load(f)["rates"]["INR"]))
        return _c[1]
    except Exception: return float(os.getenv("USDINR_SPOT", "88"))

_rc = (0, None)
def display_rates():
    """INR -> currency conversion table for the UI display-currency selector (ECB data, cached 1h)."""
    global _rc
    if time.time() - _rc[0] < 3600 and _rc[1]: return _rc[1]
    try:
        with urllib.request.urlopen("https://api.frankfurter.dev/v1/latest?base=INR&symbols=USD,EUR,GBP,JPY,SGD,AED,CHF", timeout=5) as f:
            rates = {k: float(v) for k, v in json.load(f)["rates"].items()}
    except Exception:                                      # approximate crosses off the USD/INR spot
        u = 1 / usdinr()
        rates = {"USD": u, "EUR": u * .91, "GBP": u * .79, "JPY": u * 149, "SGD": u * 1.34, "AED": u * 3.6725, "CHF": u * .88}
    rates["INR"] = 1.0; _rc = (time.time(), rates)
    return rates
