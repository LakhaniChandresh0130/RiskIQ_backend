"""RiskIQ engine v2. Works for any portfolio. No NxN matrices are built, so cost is O(days x instruments)."""
import os, time, zlib
import numpy as np, pandas as pd
from scipy.stats import norm, chi2

CR, FX = 1e7, "INR=X"
LIMITS = {"warn": 0.02, "crit": 0.03}                      # 1-day 99% VaR as share of gross exposure
SCENARIOS = {
 "Equity crash -20%": {"eq_in": -.20, "eq_gl": -.20, "fx": .03},
 "Rates +200 bps": {"dy": .02, "eq_in": -.05, "eq_gl": -.07},
 "INR depreciation +10%": {"fx": .10},
 "Oil +30%": {"sector": {"Energy": .10, "Technology": -.05, "IT": -.05}, "eq_in": -.03, "eq_gl": -.03, "comm": .05},
 "2008-style GFC": {"eq_in": -.35, "eq_gl": -.40, "fx": .12, "comm": -.25, "dy": -.015},
 "COVID Mar-2020": {"eq_in": -.30, "eq_gl": -.30, "fx": .05, "dy": -.01},
}
K = "symbol name cls ccy sector region value yf dur".split()
_D = [("RELIANCE","Reliance Industries","Equity","INR","Energy","IN",6,"RELIANCE.NS",0),("HDFCBANK","HDFC Bank","Equity","INR","Financials","IN",7,"HDFCBANK.NS",0),
 ("ICICIBANK","ICICI Bank","Equity","INR","Financials","IN",6,"ICICIBANK.NS",0),("TCS","Tata Consultancy","Equity","INR","IT","IN",5,"TCS.NS",0),
 ("INFY","Infosys","Equity","INR","IT","IN",4,"INFY.NS",0),("AAPL","Apple","Equity","USD","Technology","GL",5,"AAPL",0),
 ("MSFT","Microsoft","Equity","USD","Technology","GL",5,"MSFT",0),("NVDA","NVIDIA","Equity","USD","Technology","GL",4,"NVDA",0),
 ("JPM","JPMorgan Chase","Equity","USD","Financials","GL",3,"JPM",0),("IEF","US Treasury 7-10Y ETF","Bond","USD","Rates","GL",4,"IEF",7.5),
 ("GOLD","Gold futures","Commodity","USD","Commodities","GL",3,"GC=F",0),("USDINR","USD/INR","FX","USD","FX","GL",3,FX,0)]
DEMO_VB = {"RELIANCE.NS": (.014, .8), "HDFCBANK.NS": (.013, .8), "ICICIBANK.NS": (.014, .9), "TCS.NS": (.012, .5), "INFY.NS": (.014, .6),
           "AAPL": (.016, .8), "MSFT": (.015, .8), "NVDA": (.028, 1.2), "JPM": (.015, .9), "IEF": (.004, -.1), "GC=F": (.009, 0), FX: (.0025, .05)}

def demo_positions():
    return [dict(zip(K, p[:6] + (p[6] * CR,) + p[7:])) for p in _D]

def demo_large(n=5000, m=400, seed=1):
    """Synthetic book: n position lines over m instruments (India + US equities, bonds, commodities)."""
    rng = np.random.default_rng(seed); sect = ["Financials", "IT", "Energy", "Healthcare", "Consumer", "Industrials", "Materials", "Technology"]; inst = []
    for i in range(m):
        u = i % 20; s = sect[i % len(sect)]
        inst.append((f"IN{i:04d}", "Equity", "INR", "IN", s, f"IN{i:04d}.NS", 0) if u < 11 else
                    (f"US{i:04d}", "Equity", "USD", "GL", s, f"US{i:04d}", 0) if u < 18 else
                    (f"BND{i:04d}", "Bond", "USD", "GL", "Rates", f"BND{i:04d}", float(3 + i % 6)) if u < 19 else
                    (f"CMD{i:04d}", "Commodity", "USD", "GL", "Commodities", f"CMD{i:04d}", 0))
    vals = rng.lognormal(np.log(.15 * CR), .8, n)
    return [dict(symbol=a, name=a, cls=b, ccy=c, sector=e, region=d, value=float(vals[j]), yf=f, dur=g)
            for j, (a, b, c, d, e, f, g) in enumerate(inst[k] for k in rng.integers(0, m, n))]

# ------------------------------------------------------------------ market data (cached per instrument)
_RAW, _SRC, _SEC, _M, _IDX, _LIVE = {}, {}, {}, None, None, True
def _index():
    global _IDX
    if _IDX is None: _IDX = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=750)
    return _IDX
def _market():
    global _M
    if _M is None:
        sd = np.full(len(_index()), .008); sd[-15:] = .02    # demo: volatility regime shift in the last 15 days
        _M = np.random.default_rng(42).standard_normal(len(sd)) * sd
    return _M
def _sec(name):
    if name in ("FX", "Rates", "Commodities"): return 0
    if name not in _SEC: _SEC[name] = np.random.default_rng(zlib.crc32(name.encode())).standard_normal(len(_index())) * .006
    return _SEC[name]
def _vb(k, cls):
    if k in DEMO_VB: return DEMO_VB[k]
    h = zlib.crc32(k.encode())
    return {"Bond": (.004, -.1), "Commodity": (.009, 0), "FX": (.0025, .05)}.get(cls, (.012 + (h % 1000) / 50000, .6 + ((h >> 10) % 1000) / 1250))
def _synth(k, cls, sector):
    vol, beta = _vb(k, cls); rng = np.random.default_rng(zlib.crc32(k.encode()))
    return pd.Series(beta * _market() + _sec(sector) + rng.standard_normal(len(_index())) * vol * .6, index=_index())
def _fetch_live(keys):
    global _LIVE
    if not _LIVE: return
    try:
        import yfinance as yf
        for i in range(0, len(keys), 100):
            b = keys[i:i + 100]; px = yf.download(b, period="4y", auto_adjust=True, progress=False)["Close"]
            if isinstance(px, pd.Series): px = px.to_frame(b[0])
            for k in px.columns:
                s = px[k].dropna()
                if len(s) > 500:
                    r = np.log(s / s.shift(1)).dropna(); r.index = pd.DatetimeIndex(r.index).tz_localize(None)
                    _RAW[k] = r[~r.index.duplicated()].reindex(_index()).fillna(0); _SRC[k] = "live"
    except Exception as e:
        print("live data unavailable, using proxies:", e); _LIVE = False

def returns_for(agg):
    keys = list(agg["yf"]); need = [k for k in keys + [FX] if k not in _RAW]
    if need and os.getenv("DATA_MODE", "auto") != "synthetic": _fetch_live(need)
    meta = {r.yf: (r.cls, r.sector) for r in agg.itertuples()}
    for k in need:
        if k not in _RAW: _RAW[k] = _synth(k, *meta.get(k, ("FX", "FX"))); _SRC[k] = "proxy"
    X = np.column_stack([_RAW[k].values for k in keys])
    X[:, ((agg["ccy"] == "USD") & (agg["cls"] != "FX")).values] += _RAW[FX].values[:, None]   # USD assets carry USDINR risk too
    return pd.DataFrame(X, index=_index(), columns=keys)

# ------------------------------------------------------------------ risk maths
def _ew(n, lam=.94):
    w = lam ** np.arange(n)[::-1]; return w / w.sum()

def var_es(p, V, wt, a=.99):
    pnl = V * p; hv = -np.percentile(pnl, (1 - a) * 100); hes = -pnl[pnl <= -hv].mean()
    sig = np.sqrt((wt * p * p).sum()); z = norm.ppf(a); df = 5
    # Linear book: P&L is one-dimensional, so simulating the portfolio directly equals full multivariate MC (swap in full revaluation for options).
    sims = V * sig * np.random.default_rng(7).standard_t(df, 100000) * np.sqrt((df - 2) / df); mv = -np.percentile(sims, (1 - a) * 100)
    return {"historical": {"var": hv, "es": hes}, "parametric": {"var": z * sig * V, "es": sig * V * norm.pdf(z) / (1 - a)},
            "monte_carlo": {"var": mv, "es": -sims[sims <= -mv].mean()}}

def component_var(X, p, w, V, wt, a=.99):
    sig = np.sqrt(max((wt * p * p).sum(), 1e-18))
    return w * (X.T @ (wt * p)) / sig * norm.ppf(a) * V      # Sigma@w computed without forming Sigma; sums to parametric VaR

def var_series(p, V, days=120, a=.99, lam=.94):
    s2 = np.empty(len(p)); s2[:30] = (p[:30] ** 2).mean()
    for t in range(30, len(p)): s2[t] = lam * s2[t - 1] + (1 - lam) * p[t] ** 2
    idx = _index()
    return [{"date": str(idx[t].date()), "var": float(norm.ppf(a) * np.sqrt(s2[t]) * V)} for t in range(len(p) - days, len(p))]

def backtest(p, V, a=.99, win=250, N=250):
    pnl = V * p; x = int(sum(pnl[t] < np.percentile(pnl[t - win:t], (1 - a) * 100) for t in range(len(pnl) - N, len(pnl))))
    q, ph = 1 - a, x / N; ll0 = (N - x) * np.log(1 - q) + x * np.log(q); ll1 = (N - x) * np.log(1 - ph) + (x * np.log(ph) if x else 0)
    return {"breaches": x, "days": N, "zone": "green" if x <= 4 else "yellow" if x <= 9 else "red", "kupiec_p": float(1 - chi2.cdf(max(-2 * (ll0 - ll1), 0), 1))}

def run_scenario(name, s, agg):
    cls = agg["cls"].values; reg = agg["region"].str.lower().values
    eq = np.where(reg == "in", s.get("eq_in", 0), s.get("eq_gl", 0)) + agg["sector"].map(s.get("sector", {})).fillna(0).values
    sh = np.select([cls == "Equity", cls == "Commodity", cls == "Bond"], [eq, s.get("comm", 0), -agg["dur"].values * s.get("dy", 0)], 0.0)
    fx = s.get("fx", 0); tot = np.where(cls == "FX", fx, np.where(agg["ccy"].values == "USD", (1 + sh) * (1 + fx) - 1, sh))
    pnl = agg["value"].values * tot; o = np.argsort(pnl)[:3]; nav = float(np.abs(agg["value"].values).sum())
    return {"name": name, "loss": float(pnl.sum()), "pct": float(pnl.sum() / nav), "top": [{"symbol": agg["symbol"].iloc[i], "pnl": float(pnl[i])} for i in o]}

def cr(x): return f"₹{x / CR:,.2f} cr"

def detect(V, series, agg, R, stress, as_of, lim):
    out, vals = [], [x["var"] for x in series]; var = vals[-1]; u = var / V
    top = agg.nlargest(3, "pct"); drv = ", ".join(f"{r.symbol} ({r.pct * 100:.0f}%)" for r in top.itertuples())
    def add(sev, rule, title, text): out.append(dict(key=f"{as_of}-{rule}-{sev}", severity=sev, rule=rule, title=title, explanation=text, as_of=as_of))
    if u >= lim["crit"]: add("critical", "var_limit", "VaR above critical limit", f"1-day 99% VaR is {cr(var)} ({u*100:.2f}% of exposure), above the {lim['crit']*100:.1f}% critical limit. Top drivers: {drv}.")
    elif u >= lim["warn"]: add("warning", "var_limit", "VaR above warning limit", f"1-day 99% VaR is {cr(var)} ({u*100:.2f}% of exposure), above the {lim['warn']*100:.1f}% warning limit. Top drivers: {drv}.")
    p95 = np.percentile(vals[-91:-1], 95)
    if var > p95: add("warning", "var_spike", "Unusual risk increase", f"VaR rose {(var / vals[-6] - 1) * 100:.0f}% over 5 days and is above its 90-day 95th percentile ({cr(p95)}). Top drivers: {drv}.")
    eq = agg[agg["cls"] == "Equity"].nlargest(30, "value")["yf"].tolist(); n = len(eq)
    if n >= 5:
        avg = lambda d: (d.corr().values.sum() - n) / (n * (n - 1)); rec, base = avg(R[eq].tail(20)), avg(R[eq].iloc[-140:-20])
        if rec > base + .15: add("warning", "corr_jump", "Diversification weakening", f"Average correlation of the largest equities is {rec:.2f} over 20 days vs {base:.2f} over the prior 120 days.")
    t = top.iloc[0]
    if t["pct"] > .35: add("warning", "concentration", "Risk concentration", f"{t['symbol']} contributes {t['pct'] * 100:.0f}% of portfolio VaR.")
    w = min(stress, key=lambda s: s["pct"])
    if w["pct"] < -.15: add("critical" if w["pct"] < -.25 else "warning", "stress_loss", "Large stress-test loss", f"'{w['name']}' would lose {cr(-w['loss'])} ({-w['pct'] * 100:.1f}% of exposure).")
    return sorted(out, key=lambda a: a["severity"] != "critical")

def _grp(agg, col, top=None):
    g = agg.groupby(col)["comp_var"].sum().sort_values(ascending=False); tot = g.sum() or 1
    it = [{"key": str(k), "var": float(x), "pct": float(x / tot)} for k, x in g.items()]
    if top and len(it) > top:
        rest = it[top:]; it = it[:top] + [{"key": f"Others ({len(rest)})", "var": sum(i["var"] for i in rest), "pct": sum(i["pct"] for i in rest)}]
    return it

def analyze(positions, lim=None, extra=None):
    """positions: list of dicts with keys K. Returns (snapshot, aggregated frame)."""
    lim = lim or LIMITS; scen = {**SCENARIOS, **(extra or {})}; t0 = time.perf_counter(); df = pd.DataFrame(positions)
    agg = df.groupby("yf", as_index=False).agg(symbol=("symbol", "first"), name=("name", "first"), cls=("cls", "first"), ccy=("ccy", "first"),
          sector=("sector", "first"), region=("region", "first"), dur=("dur", "first"), value=("value", "sum"), lines=("value", "size"))
    R = returns_for(agg); X = R.values; v = agg["value"].values; V = float(np.abs(v).sum()); w = v / V
    p = X @ w; wt = _ew(len(p)); comp = component_var(X, p, w, V, wt)
    agg["comp_var"], agg["pct"], agg["weight"] = comp, comp / (comp.sum() or 1), w
    series = var_series(p, V); as_of = str(_index()[-1].date())
    stress = sorted([run_scenario(k, s, agg) for k, s in scen.items()], key=lambda s: s["loss"])
    live = sum(_SRC.get(k) == "live" for k in agg["yf"]); n = len(agg)
    snap = dict(as_of=as_of, nav=V, limits=dict(lim), methods=var_es(p, V, wt), var_series=series, backtest=backtest(p, V), stress=stress,
        attribution={"position": _grp(agg, "symbol", 15), "sector": _grp(agg, "sector", 15), "asset_class": _grp(agg, "cls"), "currency": _grp(agg, "ccy")},
        alerts=detect(V, series, agg, R, stress, as_of, lim), n_lines=int(len(df)), n_instruments=n, data_quality={"live": int(live), "proxy": int(n - live)},
        data_source="live market data" if live == n else "synthetic demo data" if live == 0 else f"{live} live / {n - live} proxy series",
        positions=agg.sort_values("pct", ascending=False)[["symbol", "name", "cls", "ccy", "sector", "value", "weight", "comp_var", "pct"]]
                     .round({"value": 0, "weight": 6, "comp_var": 0, "pct": 6}).to_dict("records"))
    snap["compute_ms"] = round((time.perf_counter() - t0) * 1000)
    return snap, agg

def refresh_market_data():
    """Drop cached returns so the next analysis re-fetches prices (called by the scheduler)."""
    global _LIVE
    _RAW.clear(); _SRC.clear(); _LIVE = True
