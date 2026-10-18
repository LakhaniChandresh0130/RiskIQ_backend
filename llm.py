"""LLM providers for the risk analyst: Groq (OpenAI-compatible, free tier) first, then Anthropic, else None (rule-based fallback)."""
import os, json, urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def provider(): return "groq" if os.getenv("GROQ_API_KEY") else "claude" if os.getenv("ANTHROPIC_API_KEY") else None

def _post(url, payload, key):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as f: return json.load(f)

def groq_chat(msg, tools, system, call_tool, post=_post):
    key, model = os.environ["GROQ_API_KEY"], os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    fns = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": msg}]; used = []
    for _ in range(5):
        m = post(GROQ_URL, {"model": model, "messages": msgs, "tools": fns, "tool_choice": "auto", "temperature": 0.1, "max_tokens": 900}, key)["choices"][0]["message"]
        calls = m.get("tool_calls") or []
        if not calls: return m.get("content") or "", used
        msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        for c in calls:
            name = c["function"]["name"]; used.append(name)
            try: out = call_tool(name, json.loads(c["function"].get("arguments") or "{}"))
            except Exception as e: out = {"error": str(e)}
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(out, default=str)[:6000]})   # keep within free-tier token limits
    return "Stopped after too many tool steps.", used

def claude_chat(msg, tools, system, call_tool):
    import anthropic
    c = anthropic.Anthropic(); msgs = [{"role": "user", "content": msg}]; used = []
    for _ in range(6):
        r = c.messages.create(model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"), max_tokens=1200, system=system, tools=tools, messages=msgs)
        if r.stop_reason != "tool_use": return "".join(b.text for b in r.content if b.type == "text"), used
        msgs.append({"role": "assistant", "content": r.content}); res = []
        for b in r.content:
            if b.type == "tool_use": used.append(b.name); res.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(call_tool(b.name, b.input), default=str)})
        msgs.append({"role": "user", "content": res})
    return "Stopped after too many tool steps.", used

def ask(msg, system, tools, call_tool):
    """Returns (answer, tools_used, mode) or None when no provider is configured or the call fails (caller falls back to rules)."""
    p = provider()
    if not p: return None
    try:
        a, used = (groq_chat if p == "groq" else claude_chat)(msg, tools, system, call_tool); return a, used, p
    except Exception as e:
        print(f"{p} call failed, using rule-based answer:", e); return None
