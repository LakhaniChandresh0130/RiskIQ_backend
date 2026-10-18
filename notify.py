"""Alert delivery: Telegram bot and/or SMTP email, configured by env. Failures are logged, never raised.

Telegram setup: message @BotFather, /newbot, copy the token into TELEGRAM_BOT_TOKEN.
Send any message to your bot, then open https://api.telegram.org/bot<token>/getUpdates
to find your chat_id and put it in TELEGRAM_CHAT_ID."""
import os, json, smtplib, urllib.request
from email.message import EmailMessage

def _telegram(text, telegram_bot_token=None, telegram_chat_id=None):
    # Use portfolio-specific credentials if provided, otherwise fall back to env vars
    tok = telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat = telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat): return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    urllib.request.urlopen(urllib.request.Request(url, body, {"Content-Type": "application/json"}), timeout=10)
def _email(subject, text):
    host, to = os.getenv("SMTP_HOST"), os.getenv("ALERT_EMAIL_TO")
    if not (host and to): return
    m = EmailMessage(); m["Subject"], m["To"] = subject, to; m["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "riskiq@localhost")); m.set_content(text)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=15) as s:
        s.starttls()
        if os.getenv("SMTP_USER"): s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASS", ""))
        s.send_message(m)
def deliver(subject, text, telegram_bot_token=None, telegram_chat_id=None):
    for fn, args in ((_telegram, (f"{subject}\n{text}", telegram_bot_token, telegram_chat_id)), (_email, (subject, text))):
        try: fn(*args)
        except Exception as e: print("notification failed:", e)
def send_all(alerts, portfolio, telegram_bot_token=None, telegram_chat_id=None):
    for a in alerts: deliver(f"[{a['severity'].upper()}] {portfolio}: {a['title']}", a["explanation"], telegram_bot_token, telegram_chat_id)
