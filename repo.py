"""Business data access: tenancy, roles, portfolios, maker-checker limits and scenarios, alerts, audit."""
import json, time, uuid
ROLES = ("super_admin", "admin", "risk_manager", "analyst", "viewer", "auditor")
PERM = {"read": ROLES, "write": ("super_admin", "admin", "risk_manager", "analyst"), "approve": ("super_admin", "admin", "risk_manager"), "audit": ("super_admin", "admin", "auditor"), "admin": ("super_admin", "admin",)}
COLS = "symbol name cls ccy sector region value yf dur".split()
now, uid = time.time, lambda: str(uuid.uuid4())
def can(role, perm): return role in PERM.get(perm, ())

def audit(db, org, user, action, entity="", entity_id="", detail=None):
    db.run("insert into audit_log values(%s,%s,%s,%s,%s,%s,%s,%s)", (uid(), org, user, action, entity, entity_id, json.dumps(detail or {}, default=str), now()))
def list_audit(db, org, limit=300):
    rows = db.all("select * from audit_log where org_id=%s order by created_at desc limit %s", (org, limit))
    for r in rows: r["detail"] = json.loads(r["detail"] or "{}")
    return rows

# ---- identity
def resolve_user(db, sub, email):
    """First sign-in: join a pending invite by email, else create a pending member record. First user of org becomes super_admin."""
    import logging
    logger = logging.getLogger(__name__)

    logger.debug("resolve_user sub=%s", sub)

    m = db.one("select * from members where user_id=%s", (sub,))
    if not m and email:
        # Check by email for existing record (whether user_id is null or placeholder or old id)
        m = db.one("select * from members where email=%s order by (case when role='super_admin' then 0 when role is not null then 1 else 2 end), created_at limit 1", (email,))
        if m:
            if m.get("user_id") != sub:
                old_sub = m.get("user_id")
                db.run("update members set user_id=%s where id=%s", (sub, m["id"]))
                if old_sub:
                    db.run("update portfolios set owner=%s where owner=%s", (sub, old_sub))
                audit(db, m["org_id"], sub, "member.join", "member", m["id"])
                logger.debug("Linked existing member for %s to user %s", email, sub)
    if not m:
        # Check if this organization exists or if any member exists
        has_any_member = db.one("select 1 as x from members limit 1")
        if not has_any_member:
            # Very first user of the entire system/org becomes super_admin
            oid = uid()
            org_name = f"{email or sub} organisation"
            db.run("insert into orgs values(%s,%s,%s)", (oid, org_name, now()))
            m = dict(id=uid(), org_id=oid, role="super_admin")
            db.run("insert into members values(%s,%s,%s,%s,%s,%s)", (m["id"], oid, sub, email, "super_admin", now()))
            audit(db, oid, sub, "org.create", "org", oid)
            logger.debug("Created first org and super_admin: %s", email)
        else:
            first_org = db.one("select id from orgs order by created_at asc limit 1")
            oid = first_org["id"] if first_org else uid()
            # New user has no role assigned -> requires approval
            mid = uid()
            try:
                # If email is None, use a placeholder to avoid NULL constraint issues
                email_to_store = email if email else f"pending-{sub[:8]}"
                db.run("insert into members values(%s,%s,%s,%s,%s,%s)", (mid, oid, sub, email_to_store, None, now()))
                m = dict(id=mid, org_id=oid, role=None)
                logger.debug("Created pending member for %s", email_to_store)
            except Exception as e:
                # Handle duplicate insertion (race condition or user already exists)
                if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                    # Fetch the existing record by email
                    m = db.one("select * from members where email=%s limit 1", (email,))
                    if m and m.get("user_id") != sub:
                        old_sub = m.get("user_id")
                        db.run("update members set user_id=%s where id=%s", (sub, m["id"]))
                        if old_sub:
                            db.run("update portfolios set owner=%s where owner=%s", (sub, old_sub))
                        logger.debug("Updated user_id for existing member %s", email)
                else:
                    logger.error(f"Error creating member: {e}")
                    raise
    # Return role as None if not assigned - this will trigger pending approval screen
    # Use the email from the member record if available, otherwise use the provided email
    actual_email = m.get("email") if m else email
    logger.debug("Resolved user sub=%s role=%s", sub, m.get("role") if m else None)
    return {"sub": sub, "email": actual_email, "org": m["org_id"], "role": m.get("role")}
def list_members(db, org):
    res = db.all("select id,user_id,email,role,created_at,org_id from members where org_id=%s order by created_at", (org,))
    if not res:
        res = db.all("select id,user_id,email,role,created_at,org_id from members order by created_at")
    return res
def invite(db, org, email, role, by):
    if role not in ROLES: raise ValueError("Unknown role")
    # Check inviter role
    inviter = db.one("select role from members where user_id=%s and org_id=%s", (by, org))
    inviter_role = inviter["role"] if inviter else None
    if inviter_role == "admin" and role in ("super_admin", "admin"):
        raise PermissionError("Admins can only invite regular members (risk_manager, analyst, viewer, auditor). Only Super Admin can invite admins.")
    if db.one("select 1 as x from members where org_id=%s and email=%s", (org, email)): raise ValueError("That email is already a member")
    try:
        db.run("insert into members values(%s,%s,%s,%s,%s,%s)", (uid(), org, None, email, role, now()))
        audit(db, org, by, "member.invite", "member", email, {"role": role})
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            raise ValueError("That email is already a member")
        raise
def set_role(db, org, mid, role, by):
    if role not in ROLES: raise ValueError("Unknown role")
    m = db.one("select * from members where id=%s and org_id=%s", (mid, org))
    if not m: raise ValueError("Member not found")
    
    actor = db.one("select role from members where user_id=%s and org_id=%s", (by, org))
    actor_role = actor["role"] if actor else None

    # Role authority rules:
    # 1. Admin cannot assign super_admin or admin roles
    # 2. Admin cannot modify existing super_admin or admin users
    if actor_role == "admin":
        if role in ("super_admin", "admin"):
            raise PermissionError("Only Super Admin can assign the Admin or Super Admin role.")
        if m["role"] in ("super_admin", "admin"):
            raise PermissionError("Admins cannot modify Admin or Super Admin accounts.")

    # Guard against removing the last super_admin or last admin
    if m["role"] == "super_admin" and role != "super_admin":
        if db.one("select count(*) as n from members where org_id=%s and role='super_admin'", (org,))["n"] < 2:
            raise ValueError("An organisation needs at least one Super Admin")
    if m["role"] == "admin" and role != "admin" and actor_role == "super_admin":
        # Allow super_admin to adjust roles
        pass

    db.run("update members set role=%s where id=%s", (role, mid)); audit(db, org, by, "member.role", "member", mid, {"role": role, "previous_role": m["role"]})

# ---- portfolios
def create_portfolio(db, org, user, name, rows, source, telegram_bot_token=None, telegram_chat_id=None):
    pid = uid(); db.run("insert into portfolios values(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (pid, org, user, name, source, len(rows), telegram_bot_token, telegram_chat_id, now()))
    db.many("insert into positions values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", [(pid, *[r[c] for c in COLS]) for r in rows]); audit(db, org, user, "portfolio.create", "portfolio", pid, {"name": name, "source": source, "rows": len(rows)}); return pid
def list_portfolios(db, org, user_id=None, role=None, filter_admin_id=None):
    """List portfolios.
    - Super Admin: sees all portfolios or can filter by specific admin.
    - Admin: sees ONLY their own portfolios.
    - Other approved roles: see team portfolios.
    """
    if role == "admin" and user_id:
        return db.all("select p.id,p.name,p.source,p.n_positions,p.telegram_bot_token,p.telegram_chat_id,p.created_at,p.owner,m.email as owner_email from portfolios p left join members m on p.owner=m.user_id where (p.org_id=%s or p.org_id is null) and p.owner=%s order by p.created_at desc", (org, user_id))
    
    if filter_admin_id and filter_admin_id != "all":
        return db.all("select p.id,p.name,p.source,p.n_positions,p.telegram_bot_token,p.telegram_chat_id,p.created_at,p.owner,m.email as owner_email from portfolios p left join members m on p.owner=m.user_id where p.owner=%s order by p.created_at desc", (filter_admin_id,))

    # For super_admin or org users: first try current org, then fallback to all available portfolios
    res = db.all("select p.id,p.name,p.source,p.n_positions,p.telegram_bot_token,p.telegram_chat_id,p.created_at,p.owner,m.email as owner_email from portfolios p left join members m on p.owner=m.user_id where p.org_id=%s order by p.created_at desc", (org,))
    if not res:
        res = db.all("select p.id,p.name,p.source,p.n_positions,p.telegram_bot_token,p.telegram_chat_id,p.created_at,p.owner,m.email as owner_email from portfolios p left join members m on p.owner=m.user_id order by p.created_at desc")
    return res

def get_portfolio(db, org, pid):
    m = db.one("select id,name,source,n_positions,telegram_bot_token,telegram_chat_id,created_at,owner,org_id from portfolios where id=%s and org_id=%s", (pid, org))
    if not m:
        m = db.one("select id,name,source,n_positions,telegram_bot_token,telegram_chat_id,created_at,owner,org_id from portfolios where id=%s", (pid,))
    return (m, db.all(f"select {','.join(COLS)} from positions where portfolio_id=%s", (pid,))) if m else None
def delete_portfolio(db, org, user, pid, role=None):
    """Delete portfolio. Admins can only delete their own portfolios. Super Admin can delete any."""
    if role == "admin":
        if not db.one("select 1 as x from portfolios where id=%s and owner=%s", (pid, user)):
            raise PermissionError("You can only delete your own portfolios")
    else:
        if not db.one("select 1 as x from portfolios where id=%s", (pid,)):
            raise ValueError("Portfolio not found")
    for t, k in (("positions", "portfolio_id"), ("portfolios", "id"), ("limits", "portfolio_id"), ("alerts", "portfolio_id")):
        db.run(f"delete from {t} where {k}=%s", (pid,))
    audit(db, org, user, "portfolio.delete", "portfolio", pid)
def update_portfolio_telegram(db, org, pid, telegram_bot_token, telegram_chat_id, user, role=None):
    """Update telegram settings. Admins can only update their own portfolios."""
    if role == "admin":
        # Admins can only update their own portfolios
        if not db.one("select 1 as x from portfolios where id=%s and org_id=%s and owner=%s", (pid, org, user)):
            raise PermissionError("You can only update your own portfolios")
    else:
        # Other roles need org-level access
        if not db.one("select 1 as x from portfolios where id=%s and org_id=%s", (pid, org)):
            raise ValueError("Portfolio not found")
    db.run("update portfolios set telegram_bot_token=%s, telegram_chat_id=%s where id=%s", (telegram_bot_token, telegram_chat_id, pid))
    audit(db, org, user, "portfolio.telegram", "portfolio", pid, {"has_bot": bool(telegram_bot_token), "has_chat": bool(telegram_chat_id)})
def get_portfolio_telegram(db, org, pid):
    m = db.one("select telegram_bot_token, telegram_chat_id from portfolios where id=%s and org_id=%s", (pid, org))
    return m if m else None

# ---- limits (maker-checker)
def active_limits(db, org, pid, default):
    r = db.one("select warn,crit from limits where org_id=%s and portfolio_id=%s and status='active' order by created_at desc limit 1", (org, pid)); return dict(r) if r else dict(default)
def list_limits(db, org, pid): return db.all("select * from limits where org_id=%s and portfolio_id=%s order by created_at desc", (org, pid))
def propose_limits(db, org, pid, warn, crit, user):
    if not (0 < warn < crit < 1): raise ValueError("Limits must satisfy 0 < warning < critical < 1")
    db.run("update limits set status='superseded' where org_id=%s and portfolio_id=%s and status='pending'", (org, pid))
    lid = uid(); db.run("insert into limits values(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (lid, org, pid, warn, crit, "pending", user, None, now())); audit(db, org, user, "limits.propose", "limits", lid, {"warn": warn, "crit": crit}); return lid
def approve_limits(db, org, lid, user):
    r = db.one("select * from limits where id=%s and org_id=%s", (lid, org))
    if not r or r["status"] != "pending": raise ValueError("No pending proposal with that id")
    if r["proposed_by"] == user: raise PermissionError("Maker-checker: a different user must approve")
    db.run("update limits set status='retired' where org_id=%s and portfolio_id=%s and status='active'", (org, r["portfolio_id"]))
    db.run("update limits set status='active', approved_by=%s where id=%s", (user, lid)); audit(db, org, user, "limits.approve", "limits", lid)

# ---- custom scenarios (maker-checker)
SHOCKS = {"eq_in", "eq_gl", "fx", "dy", "comm", "sector"}
def _validate(d):
    if not isinstance(d, dict) or not d or set(d) - SHOCKS: raise ValueError("Scenario needs at least one of: " + ", ".join(sorted(SHOCKS)))
    for k, v in d.items():
        vals = v.values() if k == "sector" and isinstance(v, dict) else [v]
        if k == "sector" and not isinstance(v, dict): raise ValueError("sector must be a mapping")
        for x in vals:
            if not isinstance(x, (int, float)) or isinstance(x, bool) or abs(x) > (0.1 if k == "dy" else 1): raise ValueError(f"Shock '{k}' is out of range")
def propose_scenario(db, org, name, definition, user):
    name = (name or "").strip()
    if not name or len(name) > 60: raise ValueError("Scenario name is required (max 60 characters)")
    _validate(definition); sid = uid()
    db.run("insert into scenarios values(%s,%s,%s,%s,%s,%s,%s,%s)", (sid, org, name, json.dumps(definition), "pending", user, None, now())); audit(db, org, user, "scenario.propose", "scenario", sid, {"name": name}); return sid
def approve_scenario(db, org, sid, user):
    r = db.one("select * from scenarios where id=%s and org_id=%s", (sid, org))
    if not r or r["status"] != "pending": raise ValueError("No pending scenario with that id")
    if r["proposed_by"] == user: raise PermissionError("Maker-checker: a different user must approve")
    db.run("update scenarios set status='approved', approved_by=%s where id=%s", (user, sid)); audit(db, org, user, "scenario.approve", "scenario", sid)
def list_scenarios(db, org):
    rows = db.all("select * from scenarios where org_id=%s order by created_at desc", (org,))
    for r in rows: r["definition"] = json.loads(r["definition"])
    return rows
def approved_scenarios(db, org): return {r["name"]: r["definition"] for r in list_scenarios(db, org) if r["status"] == "approved"}

# ---- alerts
def sync_alerts(db, org, pid, alerts):
    """Store alerts not seen before (same key = same day, rule, severity); returns only the new ones."""
    new = []
    for a in alerts:
        if not db.one("select 1 as x from alerts where org_id=%s and portfolio_id=%s and alert_key=%s", (org, pid, a["key"])):
            db.run("insert into alerts values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (uid(), org, pid, a["key"], a["severity"], a["rule"], a["title"], a["explanation"], a["as_of"], "open", None, now())); new.append(a)
    return new
def list_alerts(db, org, pid=None, statuses=("open",)):
    q = "select id,portfolio_id,severity,rule,title,explanation,as_of,status,acted_by,created_at from alerts where org_id=%s"; p = [org]
    if pid: q += " and portfolio_id=%s"; p.append(pid)
    q += f" and status in ({','.join(['%s'] * len(statuses))}) order by created_at desc limit 500"; return db.all(q, tuple(p) + tuple(statuses))
def act_alert(db, org, aid, user, status):
    if status not in ("acknowledged", "resolved"): raise ValueError("Bad status")
    if not db.one("select 1 as x from alerts where id=%s and org_id=%s", (aid, org)): raise ValueError("Alert not found")
    db.run("update alerts set status=%s, acted_by=%s where id=%s", (status, user, aid)); audit(db, org, user, "alert." + status, "alert", aid)
