"""DB layer for Supabase PostgreSQL only. Uses %s placeholders and PostgreSQL-specific types."""
import os, contextlib, logging
import psycopg2, psycopg2.extras
from psycopg2 import pool
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError: pass

logger = logging.getLogger(__name__)

DDL = """
create table if not exists orgs(id text primary key, name text, created_at double precision);
create table if not exists members(id text primary key, org_id text, user_id text, email text, role text, created_at double precision, unique(email, org_id));
create table if not exists portfolios(id text primary key, org_id text, owner text, name text, source text, n_positions integer, telegram_bot_token text, telegram_chat_id text, created_at double precision);
create table if not exists positions(portfolio_id text, symbol text, name text, cls text, ccy text, sector text, region text, value double precision, yf text, dur double precision);
create index if not exists ix_pos on positions(portfolio_id);
create table if not exists limits(id text primary key, org_id text, portfolio_id text, warn double precision, crit double precision, status text, proposed_by text, approved_by text, created_at double precision);
create table if not exists scenarios(id text primary key, org_id text, name text, definition text, status text, proposed_by text, approved_by text, created_at double precision);
create table if not exists alerts(id text primary key, org_id text, portfolio_id text, alert_key text, severity text, rule text, title text, explanation text, as_of text, status text, acted_by text, created_at double precision);
create index if not exists ix_alert on alerts(org_id, portfolio_id, alert_key);
create table if not exists audit_log(id text primary key, org_id text, user_id text, action text, entity text, entity_id text, detail text, created_at double precision);
create index if not exists ix_audit on audit_log(org_id, created_at);
create index if not exists ix_member on members(user_id);
"""

class DB:
    def __init__(s, url=None):
        s.url = url or os.getenv("DATABASE_URL")
        s.pool = None
        if not s.url or s.url == ":memory:":
            return
        try:
            s.pool = pool.ThreadedConnectionPool(minconn=2, maxconn=10, dsn=s.url, connect_timeout=5)
        except Exception as e:
            logger.warning("Could not initialize connection pool: %s", e)
            s.pool = None

        try:
            with s.tx() as cur:
                cur.execute(DDL)
        except Exception as e:
            pass

    @contextlib.contextmanager
    def tx(s):
        if not s.url:
            raise RuntimeError("Database not available. DATABASE_URL not set.")
        conn = None
        from_pool = False
        if s.pool:
            try:
                conn = s.pool.getconn()
                from_pool = True
            except Exception:
                conn = None
        if conn is None:
            conn = psycopg2.connect(s.url, connect_timeout=5)
            from_pool = False
        try:
            yield conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            conn.commit()
        except Exception:
            if conn:
                try: conn.rollback()
                except Exception: pass
            raise
        finally:
            if conn:
                if from_pool and s.pool:
                    s.pool.putconn(conn)
                else:
                    conn.close()

    def run(s, sql, p=()):
        if not s.url:
            return
        try:
            with s.tx() as cur:
                cur.execute(sql, p)
        except Exception as e:
            pass

    def many(s, sql, rows):
        if not s.url:
            return
        try:
            with s.tx() as cur:
                from psycopg2.extras import execute_values
                execute_values(cur, sql.split("values")[0] + " values %s", rows, page_size=1000)
        except Exception as e:
            pass

    def all(s, sql, p=()):
        if not s.url:
            return []
        try:
            with s.tx() as cur:
                cur.execute(sql, p)
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            return []

    def one(s, sql, p=()):
        if not s.url:
            return None
        try:
            with s.tx() as cur:
                cur.execute(sql, p)
                r = cur.fetchone()
                return dict(r) if r else None
        except Exception as e:
            return None

    def test_connection(s):
        """Test database connection."""
        if not s.url:
            return False
        try:
            with s.tx() as cur:
                cur.execute("SELECT 1")
                return True
        except Exception as e:
            return False
