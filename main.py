try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError: pass

import os, time, json, logging, tempfile, re
from contextlib import asynccontextmanager

def _is_prod():
    return os.getenv("RENDER") == "true" or os.getenv("ENV", "").lower() in ("production", "prod")

class _AccessFilter(logging.Filter):
    """Drop health probes, CORS preflights, and (in production) successful access lines."""
    _status = re.compile(r'"\s(\d{3})\s')

    def filter(self, record):
        msg = record.getMessage()
        if "OPTIONS " in msg or "/api/health" in msg:
            return False
        if _is_prod():
            m = self._status.search(msg)
            return bool(m and int(m.group(1)) >= 400)
        return True

def configure_logging():
    level_name = os.getenv("LOG_LEVEL")
    if not level_name:
        level_name = "WARNING" if _is_prod() else "INFO"
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s:%(name)s:%(message)s")
    logging.getLogger("yfinance").setLevel(logging.ERROR)
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _AccessFilter) for f in access.filters):
        access.addFilter(_AccessFilter())
    if _is_prod() and not os.getenv("ACCESS_LOG"):
        access.setLevel(logging.WARNING)
    tz_dir = os.path.join(tempfile.gettempdir(), "py-yfinance-tz")
    os.makedirs(tz_dir, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", tempfile.gettempdir())
    try:
        import yfinance as yf
        yf.set_tz_cache_location(tz_dir)
    except Exception:
        pass

configure_logging()
logger = logging.getLogger(__name__)
from fastapi import FastAPI, Depends, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import PlainTextResponse, Response, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import engine as E, ingest, connectors, repo, reports, llm, providers
from db import DB
from service import Service, NotFound

# Environment variable validation
REQUIRED_ENV_VARS = ['DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_JWT_SECRET']
OPTIONAL_ENV_VARS = ['GROQ_API_KEY', 'GROQ_MODEL', 'CORS_ORIGINS', 'SCHEDULER']

def validate_environment():
    """Validate that required environment variables are set."""
    missing = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            f"Please set them in your .env file or deployment configuration."
        )

    # Validate DATABASE_URL format
    db_url = os.getenv('DATABASE_URL')
    if not db_url.startswith('postgresql://'):
        raise EnvironmentError(
            f"DATABASE_URL must start with 'postgresql://'. Got: {db_url[:20]}..."
        )

    # Validate SUPABASE_URL format
    supabase_url = os.getenv('SUPABASE_URL')
    if not supabase_url.startswith('https://'):
        raise EnvironmentError(
            f"SUPABASE_URL must start with 'https://'. Got: {supabase_url[:20]}..."
        )

    # Set defaults for optional variables
    if not os.getenv('CORS_ORIGINS'):
        os.environ['CORS_ORIGINS'] = '*'
    if not os.getenv('GROQ_MODEL'):
        os.environ['GROQ_MODEL'] = 'llama-3.3-70b-versatile'
    if not os.getenv('SCHEDULER'):
        os.environ['SCHEDULER'] = '0'

validate_environment()
DBH = DB(); SVC = Service(DBH)

@asynccontextmanager
async def lifespan(app):
    configure_logging()
    sch = None
    if os.getenv("SCHEDULER") == "1":                         # set SCHEDULER=1 on exactly one backend instance
        from apscheduler.schedulers.background import BackgroundScheduler
        sch = BackgroundScheduler(timezone="Asia/Kolkata")
        sch.add_job(SVC.refresh_all, "cron", day_of_week="mon-fri", hour=16, minute=15)   # after NSE close
        sch.add_job(SVC.refresh_all, "cron", day_of_week="tue-sat", hour=7, minute=30)    # after US close
        sch.start()
    yield
    if sch: sch.shutdown()

cors_env = os.getenv("CORS_ORIGINS", "*")
cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
if "*" not in cors_origins:
    cors_origins.append("https://riskiq-fromntend.netlify.app")

app = FastAPI(title="RiskIQ API", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"https://.*\.netlify\.app",
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.exception_handler(NotFound)
async def _nf(r, e): return JSONResponse({"detail": str(e)}, 404)
@app.exception_handler(PermissionError)
async def _pe(r, e): return JSONResponse({"detail": str(e)}, 403)
@app.exception_handler(ValueError)
async def _ve(r, e): return JSONResponse({"detail": str(e)}, 400)

_uc = {}
_jwks_client = None

def get_jwks_client():
    global _jwks_client
    if _jwks_client is None:
        import jwt
        url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        if url:
            _jwks_client = jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)
    return _jwks_client

def _claims(token):
    import jwt
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except Exception as e:
        raise
    if alg not in ("HS256", "ES256", "RS256"): raise ValueError("unsupported token algorithm")
    try:
        if alg == "HS256" and os.getenv("SUPABASE_JWT_SECRET"):
            key = os.environ["SUPABASE_JWT_SECRET"]
        else:
            jwks_client = get_jwks_client()
            if not jwks_client:
                raise ValueError("SUPABASE_URL not configured for JWKS")
            key = jwks_client.get_signing_key_from_jwt(token).key
        decode_kwargs = {
            "algorithms": [alg],
            "leeway": 120,
            "options": {"verify_iat": False}
        }
        try:
            decoded = jwt.decode(token, key, audience="authenticated", **decode_kwargs)
        except jwt.InvalidAudienceError:
            decode_kwargs["options"]["verify_aud"] = False
            decoded = jwt.decode(token, key, **decode_kwargs)
        return decoded
    except Exception as e:
        raise

def auth(authorization: str = Header(None)):
    if os.getenv("SUPABASE_JWT_SECRET") or os.getenv("SUPABASE_URL"):
        try:
            token = (authorization or "").removeprefix("Bearer ")
            if not token:
                raise HTTPException(401, "Invalid or missing token")
            c = _claims(token)
            sub, email = c["sub"], c.get("email")
            logger.debug("Auth request sub=%s", sub)

            # If email is not in JWT, try to get it from user metadata
            if not email and "user_metadata" in c:
                email = c["user_metadata"].get("email")

            if not email:
                logger.warning(f"No email found in JWT for user {sub}. Claims: {c}")
        except HTTPException:
            raise
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)}"
            raise HTTPException(401, f"Invalid or expired token: {err_msg}")
    else:
        raise HTTPException(503, "Supabase authentication not configured. Please set SUPABASE_URL and SUPABASE_JWT_SECRET environment variables.")
    hit = _uc.get(sub)
    if hit and time.time() - hit[0] < 5: return hit[1]  # Reduced cache from 30s to 5s
    try:
        u = repo.resolve_user(DBH, sub, email); _uc[sub] = (time.time(), u); return u
    except Exception as e:
        # If database connection fails, don't silently assign roles — raise a clear error
        logger.error("Error resolving user %s: %s", sub, e, exc_info=True)
        raise HTTPException(503, f"Database temporarily unavailable. Please try again in a moment.")

def need(perm):
    def dep(u=Depends(auth)):
        if not repo.can(u["role"], perm): raise HTTPException(403, "Your role is not allowed to do this")
        return u
    return dep

@app.get("/api/health")
def health():
    """Basic health check endpoint."""
    return {
        "ok": True,
        "llm": llm.provider() or "rule-based",
        "timestamp": time.time()
    }

@app.get("/api/me")
def me(u=Depends(auth)):
    """Get current user information."""
    return u

@app.get("/api/health/detailed")
def health_detailed():
    """Detailed health check with database and service status."""
    try:
        # Test database connection
        db_healthy = DBH.test_connection() if hasattr(DBH, 'test_connection') else True
    except Exception as e:
        db_healthy = False

    return {
        "status": "healthy" if db_healthy else "degraded",
        "timestamp": time.time(),
        "services": {
            "database": "ok" if db_healthy else "error",
            "llm": llm.provider() or "rule-based",
            "scheduler": "enabled" if os.getenv("SCHEDULER") == "1" else "disabled"
        },
        "environment": {
            "supabase_configured": bool(os.getenv("SUPABASE_URL")),
            "groq_configured": bool(os.getenv("GROQ_API_KEY")),
            "cors_origins": os.getenv("CORS_ORIGINS", "*")
        }
    }
@app.get("/api/fx")
def fx(): return providers.display_rates()               # INR -> currency table for the display-currency selector

# ---------------------------------------------------------------- portfolios
@app.get("/api/portfolios")
def plist(admin_id: str = None, u=Depends(need("read"))): return repo.list_portfolios(DBH, u["org"], user_id=u["sub"], role=u["role"], filter_admin_id=admin_id)

@app.post("/api/portfolios")
async def upload(request: Request, name: str = "My portfolio", filename: str = "upload.csv", telegram_bot_token: str = "", telegram_chat_id: str = "", u=Depends(need("write"))):
    body, fx = await request.body(), await run_in_threadpool(providers.usdinr)
    try: rows, rep = await run_in_threadpool(ingest.parse, body, filename, fx)
    except Exception as e: raise HTTPException(400, f"Could not read file: {e}")
    if not rows: raise HTTPException(400, "No valid rows. " + (rep["errors"][0]["error"] if rep["errors"] else ""))
    pid = await run_in_threadpool(repo.create_portfolio, DBH, u["org"], u["sub"], name, rows, "upload", telegram_bot_token or None, telegram_chat_id or None)
    try: await run_in_threadpool(SVC.analysis, u["org"], pid)
    except Exception: pass
    return {"id": pid, "report": rep}

@app.post("/api/analyze-once")
async def analyze_once(request: Request, filename: str = "upload.csv", u=Depends(need("read"))):
    """Analyse a file without saving holdings anywhere. Only an audit line (row count) is written."""
    body, fx = await request.body(), await run_in_threadpool(providers.usdinr)
    try: rows, rep = await run_in_threadpool(ingest.parse, body, filename, fx)
    except Exception as e: raise HTTPException(400, f"Could not read file: {e}")
    if not rows: raise HTTPException(400, "No valid rows. " + (rep["errors"][0]["error"] if rep["errors"] else ""))
    snap, _ = await run_in_threadpool(E.analyze, rows)
    repo.audit(DBH, u["org"], u["sub"], "analyze.once", "upload", "", {"rows": rep["rows_ok"]})
    return {**snap, "portfolio": "Uploaded file (not saved)", "report": rep}



@app.post("/api/portfolios/{pid}/delete")
def delete(pid: str, u=Depends(need("write"))): repo.delete_portfolio(DBH, u["org"], u["sub"], pid, role=u["role"]); SVC.cache.clear(); return {"ok": True}

class TelegramSettings(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

@app.get("/api/portfolios/{pid}/telegram")
def get_telegram(pid: str, u=Depends(need("read"))):
    m = repo.get_portfolio_telegram(DBH, u["org"], pid)
    return {"telegram_bot_token": m["telegram_bot_token"] if m else "", "telegram_chat_id": m["telegram_chat_id"] if m else ""}

@app.post("/api/portfolios/{pid}/telegram")
def update_telegram(pid: str, b: TelegramSettings, u=Depends(need("write"))):
    repo.update_portfolio_telegram(DBH, u["org"], pid, b.telegram_bot_token, b.telegram_chat_id, u["sub"])
    return {"ok": True}

@app.get("/api/portfolios/{pid}/snapshot")
def snapshot(pid: str, refresh: bool = False, u=Depends(need("read"))): return SVC.snapshot(u["org"], pid, force=refresh)

@app.get("/api/portfolios/{pid}/report.xlsx")
def report(pid: str, u=Depends(need("read"))):
    s = SVC.snapshot(u["org"], pid); repo.audit(DBH, u["org"], u["sub"], "report.download", "portfolio", pid)
    return Response(reports.build_xlsx(s, s["portfolio"]), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=risk_report.xlsx"})

@app.get("/api/template.csv", response_class=PlainTextResponse)
def template(): return PlainTextResponse(ingest.TEMPLATE, headers={"Content-Disposition": "attachment; filename=portfolio_template.csv"})

class Shock(BaseModel):
    eq_in: float = 0; eq_gl: float = 0; fx: float = 0; dy: float = 0; comm: float = 0

@app.post("/api/stress/custom")
def custom(b: Shock, portfolio: str, u=Depends(need("read"))): return E.run_scenario("Custom", b.model_dump(), SVC.analysis(u["org"], portfolio)[0][1])

# ---------------------------------------------------------------- governance
@app.get("/api/alerts")
def alerts(status: str = "open", portfolio: str = None, u=Depends(need("read"))): return repo.list_alerts(DBH, u["org"], portfolio, (status,))
@app.post("/api/alerts/{aid}/ack")
def ack(aid: str, u=Depends(need("write"))): repo.act_alert(DBH, u["org"], aid, u["sub"], "acknowledged"); return {"ok": True}
@app.post("/api/alerts/{aid}/resolve")
def resolve(aid: str, u=Depends(need("write"))): repo.act_alert(DBH, u["org"], aid, u["sub"], "resolved"); return {"ok": True}

class LimitIn(BaseModel): portfolio: str; warn: float; crit: float
@app.get("/api/limits")
def limits(portfolio: str, u=Depends(need("read"))): return {"active": repo.active_limits(DBH, u["org"], portfolio, E.LIMITS), "rows": repo.list_limits(DBH, u["org"], portfolio)}
@app.post("/api/limits")
def propose_limits(b: LimitIn, u=Depends(need("write"))): return {"id": repo.propose_limits(DBH, u["org"], b.portfolio, b.warn, b.crit, u["sub"])}
@app.post("/api/limits/{lid}/approve")
def approve_limits(lid: str, u=Depends(need("approve"))): repo.approve_limits(DBH, u["org"], lid, u["sub"]); return {"ok": True}

class ScenIn(BaseModel): name: str; definition: dict
@app.get("/api/scenarios")
def scenarios(u=Depends(need("read"))): return repo.list_scenarios(DBH, u["org"])
@app.post("/api/scenarios")
def propose_scenario(b: ScenIn, u=Depends(need("write"))): return {"id": repo.propose_scenario(DBH, u["org"], b.name, b.definition, u["sub"])}
@app.post("/api/scenarios/{sid}/approve")
def approve_scenario(sid: str, u=Depends(need("approve"))): repo.approve_scenario(DBH, u["org"], sid, u["sub"]); return {"ok": True}

@app.get("/api/audit")
def audit_log(u=Depends(need("audit"))): return repo.list_audit(DBH, u["org"])

class Invite(BaseModel): email: str; role: str
class RoleIn(BaseModel): role: str
@app.get("/api/members")
def members(u=Depends(need("admin"))): return repo.list_members(DBH, u["org"])
@app.post("/api/members")
def invite(b: Invite, u=Depends(need("admin"))): repo.invite(DBH, u["org"], b.email.strip().lower(), b.role, u["sub"]); return {"ok": True}
@app.post("/api/members/{mid}/role")
def role(mid: str, b: RoleIn, u=Depends(need("admin"))): repo.set_role(DBH, u["org"], mid, b.role, u["sub"]); _uc.clear(); return {"ok": True}
@app.post("/api/admin/refresh")
def refresh(u=Depends(need("admin"))): return {"portfolios_refreshed": SVC.refresh_all()}

# ---------------------------------------------------------------- connectors
@app.get("/api/connectors")
def conns(): return [{"id": "csv", "name": "CSV / Excel upload", "status": "available"},
    {"id": "kite", "name": "Zerodha Kite (holdings)", "status": "available" if os.getenv("KITE_API_KEY") else "set KITE_API_KEY and KITE_API_SECRET"},
    {"id": "upstox", "name": "Upstox / Angel One", "status": "planned"}, {"id": "api", "name": "REST push API for OMS/custodian feeds", "status": "planned"}]

@app.get("/api/connectors/kite/login")
def kite_login(u=Depends(need("write"))):
    try: return {"url": connectors.kite_login_url()}
    except Exception as e: raise HTTPException(400, str(e))

class KiteIn(BaseModel): request_token: str; telegram_bot_token: str = ""; telegram_chat_id: str = ""
@app.post("/api/connectors/kite/import")
def kite_import(b: KiteIn, u=Depends(need("write"))):
    try: rows = connectors.kite_holdings(b.request_token)
    except Exception as e: raise HTTPException(400, f"Kite import failed: {e}")
    if not rows: raise HTTPException(400, "No holdings returned")
    return {"id": repo.create_portfolio(DBH, u["org"], u["sub"], "Zerodha holdings", rows, "kite", b.telegram_bot_token or None, b.telegram_chat_id or None), "report": {"rows_ok": len(rows)}}

# ---------------------------------------------------------------- AI analyst: tools compute, the LLM only explains
TOOLS = [{"name": "get_risk_summary", "description": "Exposure, VaR/ES by method, limits, backtest.", "input_schema": {"type": "object", "properties": {}}},
 {"name": "get_attribution", "description": "Risk contribution by level.", "input_schema": {"type": "object", "properties": {"level": {"type": "string", "enum": ["position", "sector", "asset_class", "currency"]}}, "required": ["level"]}},
 {"name": "run_stress", "description": "Results of all stress scenarios.", "input_schema": {"type": "object", "properties": {}}},
 {"name": "get_alerts", "description": "Current risk alerts with explanations.", "input_schema": {"type": "object", "properties": {}}}]
SYSTEM = "You are a portfolio risk analyst. Use tools for every number; never calculate or estimate yourself. Amounts are INR; show in crore (1 cr = 1e7). Be concise."

def call_tool(name, a, s):
    if name == "get_risk_summary": return {k: s[k] for k in ("as_of", "nav", "methods", "limits", "backtest", "data_quality")}
    if name == "get_attribution": return s["attribution"][(a or {}).get("level", "position")][:8]
    return s["stress"] if name == "run_stress" else s["alerts"]

def rule_chat(msg, s):
    m, cr = msg.lower(), E.cr
    if any(k in m for k in ("stress", "crash", "scenario", "what if")): return "Worst scenarios: " + "; ".join(f"{x['name']} {cr(x['loss'])} ({x['pct']*100:.1f}%)" for x in s["stress"][:3]), ["run_stress"]
    if any(k in m for k in ("driver", "contribut", "position", "concentr")): return "Top risk contributors: " + ", ".join(f"{x['key']} {x['pct']*100:.0f}%" for x in s["attribution"]["position"][:5]), ["get_attribution"]
    if any(k in m for k in ("why", "alert", "increase", "spike")): return (" ".join(a["explanation"] for a in s["alerts"]) or "No active alerts."), ["get_alerts"]
    p = s["methods"]["parametric"]
    return f"Exposure {cr(s['nav'])}. 1-day 99% VaR {cr(p['var'])} ({p['var']/s['nav']*100:.2f}%), ES {cr(p['es'])}. Backtest: {s['backtest']['breaches']} breaches in 250 days ({s['backtest']['zone']}).", ["get_risk_summary"]

class Chat(BaseModel): message: str; portfolio: str
@app.post("/api/agent/chat")
def chat(b: Chat, u=Depends(need("read"))):
    s = SVC.snapshot(u["org"], b.portfolio); steps = []
    def traced(n, a):                                        # record each tool call for the "how I got this" panel
        try:
            out = call_tool(n, a, s); steps.append({"tool": n, "args": a or {}, "ok": True, "preview": json.dumps(out, default=str)[:600]}); return out
        except Exception as e:
            steps.append({"tool": n, "args": a or {}, "ok": False, "preview": str(e)[:200]}); return {"error": str(e)}
    ans = llm.ask(b.message, SYSTEM, TOOLS, traced)
    if ans is None:
        a, t = rule_chat(b.message, s)
        steps.extend({"tool": n, "args": {}, "ok": True, "preview": ""} for n in t); ans = (a, t, "rule-based")
    repo.audit(DBH, u["org"], u["sub"], "agent.chat", "portfolio", b.portfolio, {"tools": ans[1], "mode": ans[2]})
    return {"answer": ans[0], "tools": ans[1], "mode": ans[2], "steps": steps}
