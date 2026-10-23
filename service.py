"""Application service: analysis cache, alert sync + notification, scheduled refresh. No web framework imports."""
import json
import engine as E, repo, notify

class NotFound(Exception): pass

class Service:
    def __init__(s, db): s.db, s.cache = db, {}
    def analysis(s, org, pid):
        got = repo.get_portfolio(s.db, org, pid)
        if not got: raise NotFound("Portfolio not found")
        meta, pos = got
        lim, extra = repo.active_limits(s.db, org, pid, E.LIMITS), repo.approved_scenarios(s.db, org)
        key = (org, pid, meta["created_at"], lim["warn"], lim["crit"], json.dumps(extra, sort_keys=True))
        if key not in s.cache:
            if len(s.cache) > 64: s.cache.pop(next(iter(s.cache)))
            s.cache[key] = E.analyze(pos, lim, extra)
            # Get portfolio-specific Telegram credentials from meta directly
            telegram_bot_token = meta.get("telegram_bot_token")
            telegram_chat_id = meta.get("telegram_chat_id")
            notify.send_all(repo.sync_alerts(s.db, org, pid, s.cache[key][0]["alerts"]), meta["name"], telegram_bot_token, telegram_chat_id)
        return s.cache[key], meta
    def snapshot(s, org, pid):
        (snap, _), meta = s.analysis(org, pid)
        return {**snap, "portfolio": meta["name"], "alerts": repo.list_alerts(s.db, org, pid, ("open",))}
    def refresh_all(s):
        """Scheduled job: reload market data and re-run every portfolio so alerts fire without anyone opening the UI."""
        E.refresh_market_data(); s.cache.clear(); n = 0
        for r in s.db.all("select id, org_id from portfolios"):
            try: s.analysis(r["org_id"], r["id"]); n += 1
            except Exception as e: print("scheduled run failed for", r["id"], e)
        return n
