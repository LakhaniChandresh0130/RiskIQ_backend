"""CSV / Excel portfolio ingestion with vectorised validation. value is converted to INR."""
import io
import numpy as np, pandas as pd

MAX_ROWS, MAX_INSTR, EX = 200_000, 1500, {"NSE": ".NS", "BSE": ".BO"}
ALIAS = {"symbol": ("tradingsymbol", "trading_symbol", "scrip", "scrip_name", "instrument", "ticker", "stock"),
         "quantity": ("qty", "quantity_available", "net_qty", "holding_qty", "shares", "units"),
         "price": ("ltp", "last_price", "previous_closing_price", "closing_price", "close_price", "current_price", "cmp"),
         "market_value": ("current_value", "present_value"), "sector": ("industry",)}
TEMPLATE = """symbol,exchange,quantity,price,currency,asset_class,sector,name
RELIANCE,NSE,1000,2900,INR,Equity,Energy,Reliance Industries
HDFCBANK,NSE,2500,1650,INR,Equity,Financials,HDFC Bank
AAPL,NASDAQ,500,230,USD,Equity,Technology,Apple
IEF,NYSE,800,95,USD,Bond,Rates,US Treasury 7-10Y ETF
"""

def parse(content: bytes, filename="", usdinr=88.0):
    rd = pd.read_excel if filename.lower().endswith((".xlsx", ".xls")) else pd.read_csv
    df = rd(io.BytesIO(content)); df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    for k, alts in ALIAS.items():                               # accept common broker export headings
        if k not in df:
            for a in alts:
                if a in df: df[k] = df[a]; break
    if "symbol" not in df: raise ValueError("Missing required column: symbol. Columns found: " + ", ".join(map(str, df.columns)))
    if len(df) > MAX_ROWS: raise ValueError(f"Too many rows (max {MAX_ROWS:,})")
    col = lambda c, d: df[c] if c in df else pd.Series(d, index=df.index)
    sym = df["symbol"].fillna("").astype(str).str.strip().str.upper(); ex = col("exchange", "NSE").fillna("NSE").astype(str).str.upper()
    local = ex.isin(list(EX)); cur = col("currency", "").fillna("").astype(str).str.upper(); cur = cur.where(cur != "", np.where(local, "INR", "USD"))
    val = pd.to_numeric(col("market_value", np.nan), errors="coerce")
    val = val.fillna(pd.to_numeric(col("quantity", np.nan), errors="coerce") * pd.to_numeric(col("price", np.nan), errors="coerce"))
    val = val * np.where(cur == "USD", usdinr, 1.0)
    bad = val.isna() | ~np.isfinite(val) | sym.isin(["", "NAN"]) | (val == 0)
    errs = [{"row": int(i) + 2, "error": "needs a symbol and market_value (or quantity and price)"} for i in df.index[bad][:50]]
    cls = col("asset_class", "Equity").fillna("Equity").astype(str).str.strip().str.title().replace({"Fx": "FX"})
    cls = cls.where(cls.isin(["Equity", "Bond", "Commodity", "FX"]), "Equity")
    is_fx = (cls == "FX") | sym.isin(["USDINR", "EURINR", "GBPINR", "EURUSD", "GBPUSD", "USDJPY", "JPYINR"])
    is_bond_comm = cls.isin(["Bond", "Commodity"])
    has_spaces = sym.str.contains(r"\s")
    base_yf = np.where(sym.str.contains(r"[.=^]"), sym, np.where(is_fx, sym + "=X", np.where(is_bond_comm | has_spaces, sym, sym + ex.map(EX).fillna(""))))
    yf = pd.Series(base_yf, index=df.index)
    out = pd.DataFrame({"symbol": sym, "name": col("name", "").fillna("").astype(str), "cls": cls, "ccy": cur,
        "sector": col("sector", "Unclassified").fillna("Unclassified").astype(str), "region": np.where(local, "IN", "GL"),
        "value": val, "yf": yf, "dur": pd.to_numeric(col("duration", 0), errors="coerce").fillna(0)})[~bad]
    out["name"] = out["name"].where(out["name"] != "", out["symbol"])
    if out["yf"].nunique() > MAX_INSTR: raise ValueError(f"Too many distinct instruments (max {MAX_INSTR})")
    return out.to_dict("records"), {"rows_total": int(len(df)), "rows_ok": int(len(out)), "instruments": int(out["yf"].nunique()), "errors": errs}
