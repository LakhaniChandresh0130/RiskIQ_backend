import time, numpy as np, pandas as pd, engine as E, ingest

def frame(rows): return pd.DataFrame(rows)

def test_component_var_sums_to_parametric_var():
    s, agg = E.analyze(E.demo_positions())
    assert abs(agg["comp_var"].sum() - s["methods"]["parametric"]["var"]) < 1e-6 * s["nav"]

def test_series_matches_headline_var():
    s, _ = E.analyze(E.demo_positions())
    assert abs(s["var_series"][-1]["var"] / s["methods"]["parametric"]["var"] - 1) < 1e-4

def test_es_exceeds_var_and_confidence_monotonic():
    p = np.random.default_rng(0).standard_normal(750) * .01; wt = E._ew(750)
    a, b = E.var_es(p, 1e9, wt, .95), E.var_es(p, 1e9, wt, .99)
    for m in a: assert a[m]["es"] >= a[m]["var"] and b[m]["var"] > a[m]["var"]

def test_stress_exact_values():
    agg = frame([dict(yf="A", symbol="A", cls="Equity", ccy="INR", sector="X", region="IN", dur=0, value=100e7),
                 dict(yf="B", symbol="B", cls="Equity", ccy="USD", sector="X", region="GL", dur=0, value=100e7)])
    r = E.run_scenario("t", {"eq_in": -.2, "eq_gl": -.2, "fx": .1}, agg)
    assert abs(r["loss"] - (-20e7 + (0.8 * 1.1 - 1) * 100e7)) < 1          # -32 cr: INR leg -20%, USD leg 0.8*1.1-1

def test_bond_duration_shock():
    agg = frame([dict(yf="B", symbol="B", cls="Bond", ccy="INR", sector="Rates", region="IN", dur=5, value=100e7)])
    assert abs(E.run_scenario("t", {"dy": .02}, agg)["pct"] + .10) < 1e-9

def test_backtest_not_red_on_calibrated_model():
    p = np.random.default_rng(3).standard_normal(750) * .01
    assert E.backtest(p, 1e9)["zone"] != "red"

def test_usd_asset_carries_fx_risk():
    a = frame([dict(yf="AAPL", symbol="AAPL", cls="Equity", ccy="USD", sector="Technology", region="GL", dur=0, value=1)])
    b = a.assign(ccy="INR"); assert not np.allclose(E.returns_for(a).values, E.returns_for(b).values)

def test_ingest_parses_and_reports_errors():
    csv = b"symbol,exchange,quantity,price,currency\nRELIANCE,NSE,10,100,INR\nAAPL,NASDAQ,10,10,USD\n,NSE,1,1,INR\nTCS,NSE,,,\n"
    rows, rep = ingest.parse(csv, "a.csv", usdinr=80)
    assert rep["rows_ok"] == 2 and len(rep["errors"]) == 2
    assert rows[0]["yf"] == "RELIANCE.NS" and rows[1]["yf"] == "AAPL" and rows[1]["value"] == 8000

def test_large_book_is_fast_and_consistent():
    pos = E.demo_large(5000, 400); t = time.perf_counter(); s, agg = E.analyze(pos); dt = time.perf_counter() - t
    assert s["n_lines"] == 5000 and s["n_instruments"] <= 400 and dt < 5
    assert abs(agg["comp_var"].sum() - s["methods"]["parametric"]["var"]) < 1e-6 * s["nav"]
    print(f"\n5,000 lines / {s['n_instruments']} instruments analysed in {dt*1000:.0f} ms")
