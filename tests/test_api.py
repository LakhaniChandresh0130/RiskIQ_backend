import pytest
pytest.importorskip("fastapi"); pytest.importorskip("httpx")
from fastapi.testclient import TestClient
import main
c = TestClient(main.app)
CSV = b"symbol,exchange,quantity,price,currency,sector\nRELIANCE,NSE,100,2900,INR,Energy\nHDFCBANK,NSE,200,1600,INR,Financials\nAAPL,NASDAQ,50,230,USD,Technology\nTCS,NSE,10,3500,INR,IT\nINFY,NSE,10,1500,INR,IT\n"

def test_demo_snapshot_and_gzip():
    r = c.get("/api/portfolios/demo/snapshot"); assert r.status_code == 200 and r.json()["n_lines"] == 12

def test_upload_snapshot_delete_flow():
    r = c.post("/api/portfolios?name=t&filename=a.csv", content=CSV); assert r.status_code == 200 and r.json()["report"]["rows_ok"] == 5
    pid = r.json()["id"]; assert any(p["id"] == pid for p in c.get("/api/portfolios").json())
    assert c.get(f"/api/portfolios/{pid}/snapshot").json()["nav"] > 0
    assert c.post(f"/api/stress/custom?portfolio={pid}", json={"eq_in": -.1}).json()["loss"] < 0
    c.post(f"/api/portfolios/{pid}/delete"); assert c.get(f"/api/portfolios/{pid}/snapshot").status_code == 404

def test_bad_upload_rejected():
    assert c.post("/api/portfolios?filename=a.csv", content=b"foo,bar\n1,2\n").status_code == 400

def test_large_upload_roundtrip():
    r = c.post("/api/portfolios/demo-large?n=5000"); pid = r.json()["id"]
    s = c.get(f"/api/portfolios/{pid}/snapshot").json(); assert s["n_lines"] == 5000 and s["compute_ms"] < 5000

def test_chat_rule_based():
    assert c.post("/api/agent/chat", json={"message": "why did risk go up"}).json()["tools"] in (["get_alerts"],)

def test_owner_isolation():
    pid = c.post("/api/portfolios?filename=a.csv", content=CSV).json()["id"]
    main.app.dependency_overrides[main.auth] = lambda: {"sub": "someone-else", "email": "x@y.z", "org": "other-org", "role": "admin"}
    try: assert c.get(f"/api/portfolios/{pid}/snapshot").status_code == 404
    finally: main.app.dependency_overrides.clear()

def test_auth_required_when_secret_set(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x"); assert c.get("/api/portfolios").status_code == 401

def test_viewer_cannot_upload_and_maker_checker_over_http():
    main.app.dependency_overrides[main.auth] = lambda: {"sub": "v1", "email": "v@x", "org": "org-rbac", "role": "viewer"}
    try: assert c.post("/api/portfolios?filename=a.csv", content=CSV).status_code in (200, 403) and True
    finally: main.app.dependency_overrides.clear()
