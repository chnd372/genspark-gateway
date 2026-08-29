import os, json, time, random, glob, hashlib, asyncio
import aiohttp
from aiohttp import web

GENSERVER = "https://www.genspark.ai"
API_KEY = os.environ.get("GS_API_KEY", "sk-gs-CHANGE-ME")
PORT = int(os.environ.get("PORT", 20132))
ACCOUNTS_DIR = "/opt/data/gs_accounts"

DEFAULT_SESSION = os.environ.get("GS_SESSION", "")

DEAD_KEYWORDS = [
    "not logged in", "unauthorized", "authentication", "401",
    "session expired", "invalid session", "please log in", "sign in",
]

MODELS = [
    "auto",
    "gpt-5-pro", "gpt-5.1-low", "gpt-5.1-medium", "gpt-5.1-high",
    "gpt-5.4", "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.2", "gpt-5.2-pro", "gpt-5.4-pro", "gpt-5.5-pro",
    "o3-pro",
    "claude-sonnet-4", "claude-sonnet-5", "claude-sonnet-4-6", "claude-opus-5",
    "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-5", "claude-opus-4-1",
    "claude-opus-4-6", "claude-opus-4-5", "claude-4-5-haiku",
    "gemini-2.5-flash", "gemini-2.5-pro", "gemini-3-flash-preview",
    "gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview",
    "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
    "deep-seek-v4-pro", "deep-seek-v4-flash", "deepseek-v4-pro-0813",
    "trinity-large-thinking",
    "minimax-m2p7", "minimax-m3",
    "kimi-k3", "kimi-k2p6", "kimi-k2-instruct", "groq-kimi-k2-instruct",
    "qwen-3.8-max", "solar-pro4", "nemotron-3-ultra",
    "glm-5p2", "glm-5p3-openrouter", "glm-5p3-flash-baseten",
    "grok-4-0709", "grok-4.20-0309-reasoning", "grok-4.20-0309-non-reasoning",
    "grok-4.5", "grok-4.6",
]


def load_accounts():
    accounts = []
    if os.path.isdir(ACCOUNTS_DIR):
        for f in sorted(glob.glob(os.path.join(ACCOUNTS_DIR, "*.json"))):
            try:
                with open(f) as fh:
                    d = json.load(fh)
                if d.get("session_id"):
                    accounts.append({
                        "file": f,
                        "session_id": d["session_id"],
                        "email": d.get("email", "?"),
                        "dead": d.get("dead", False),
                    })
            except Exception:
                pass
    if not accounts:
        accounts = [{"file": None, "session_id": DEFAULT_SESSION, "email": "default", "dead": False}]
    return accounts


def pick_account():
    live = [a for a in load_accounts() if not a.get("dead")]
    if not live:
        live = load_accounts()
    return random.choice(live)


def headers_for(session):
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Content-Type": "application/json",
        "Cookie": session,
        "Origin": "https://www.genspark.ai",
        "Referer": "https://www.genspark.ai/tools/ai-chat",
    }


def check_auth(req):
    auth = req.headers.get("Authorization", "")
    return auth.replace("Bearer ", "") == API_KEY


def mark_dead(account):
    if account.get("file"):
        try:
            with open(account["file"]) as fh:
                d = json.load(fh)
            d["dead"] = True
            d["dead_at"] = time.time()
            with open(account["file"], "w") as fh:
                json.dump(d, fh, indent=2)
        except Exception:
            pass
    account["dead"] = True


def looks_dead(raw):
    low = raw.lower()
    return any(k in low for k in DEAD_KEYWORDS)


TIMEOUT_MARKERS = ["didn't respond in time", "try again in a moment", "timeout", "timed out"]


def parse_stream(raw):
    """Extract content + usage from SSE stream. Prefers message_field (full text),
    falls back to concatenated deltas, then last non-empty message_result."""
    content = ""
    deltas = []
    results = []
    usage = {}
    for block in raw.split("\n\n"):
        if not block.startswith("data: "):
            continue
        try:
            d = json.loads(block[6:])
        except Exception:
            continue
        t = d.get("type")
        if t == "message_field" and d.get("field_name") == "content":
            content = d.get("field_value", "")
        elif t == "message_field_delta" and d.get("field_name") == "content":
            deltas.append(d.get("delta", ""))
        elif t == "message_result":
            m = d.get("message", {})
            if m.get("content"):
                results.append(m["content"])
            ss = m.get("session_state") or {}
            u = ss.get("_llm_usage")
            if u:
                usage = {
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "total_tokens": u.get("total_tokens", 0),
                }
    final = content or "".join(deltas) or (results[-1] if results else "")
    timed_out = any(k in final.lower() for k in TIMEOUT_MARKERS) and not content and not deltas
    return final, usage, timed_out


def short_id(s):
    return hashlib.md5(s.encode()).hexdigest()[:8]


async def handle_models(req):
    if not check_auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    data = [{"id": m, "object": "model", "created": 1787979786, "owned_by": "genspark"} for m in MODELS]
    return web.json_response({"object": "list", "data": data})


async def handle_credit(req):
    if not check_auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    total = 0
    per = []
    for acc in load_accounts():
        try:
            async with aiohttp.ClientSession(headers=headers_for(acc["session_id"])) as sess:
                async with sess.get(f"{GENSERVER}/api/payment/get_credit_balance", timeout=aiohttp.ClientTimeout(20)) as resp:
                    data = await resp.json()
            bal = data.get("data", {}).get("balance", 0)
            total += bal
            per.append({"email": acc["email"], "balance": bal, "dead": acc.get("dead", False)})
        except Exception as e:
            per.append({"email": acc["email"], "balance": 0, "error": str(e)[:60]})
    return web.json_response({"total_balance": total, "accounts": per})


async def handle_import(req):
    if not check_auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    session_id = (body.get("session_id") or "").strip()
    email = (body.get("email") or "unknown").strip()
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)
    if not session_id.startswith("session_id="):
        session_id = "session_id=" + session_id
    if "gslogin" not in session_id:
        session_id = session_id + "; gslogin=1"
    acc_id = short_id(session_id)
    os.makedirs(ACCOUNTS_DIR, exist_ok=True)
    path = os.path.join(ACCOUNTS_DIR, f"{acc_id}.json")
    with open(path, "w") as fh:
        json.dump({"email": email, "session_id": session_id, "added_at": time.time(), "dead": False}, fh, indent=2)
    return web.json_response({"status": "ok", "file": path, "email": email, "account_id": acc_id})


async def handle_accounts(req):
    if not check_auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    return web.json_response({"accounts": load_accounts()})


async def dash_data():
    accounts = load_accounts()
    live = [a for a in accounts if not a.get("dead")]

    async def get_bal(acc):
        try:
            async with aiohttp.ClientSession(headers=headers_for(acc["session_id"])) as sess:
                async with sess.get(f"{GENSERVER}/api/payment/get_credit_balance", timeout=aiohttp.ClientTimeout(15)) as resp:
                    data = await resp.json()
            bal = data.get("data", {}).get("balance", 0)
            email_check = ""
            return {"email": acc["email"], "balance": bal, "dead": acc.get("dead", False), "error": ""}
        except Exception as e:
            return {"email": acc["email"], "balance": 0, "dead": acc.get("dead", False), "error": str(e)[:60]}

    rows = await asyncio.gather(*[get_bal(a) for a in accounts])
    total = sum(r["balance"] for r in rows if not r["dead"])
    return {
        "accounts_total": len(accounts),
        "alive": len(live),
        "points": total,
        "accounts": rows,
        "models": MODELS,
        "upstream": "www.genspark.ai",
        "routes": ["POST /v1/chat/completions", "GET /v1/models", "GET /v1/credit", "GET /v1/accounts", "POST /v1/import-account"],
    }


DASH_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Genspark Gateway</title>
<style>
  body{background:#0d1117;color:#c9d1d9;font-family:ui-monospace,Menlo,Consolas,monospace;margin:24px;}
  h1{color:#58a6ff;font-size:20px;margin:0 0 4px;}
  .sub{color:#8b949e;font-size:12px;margin-bottom:18px;}
  .stats{display:flex;gap:12px;margin-bottom:18px;flex-wrap:wrap;}
  .stat{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 16px;}
  .stat b{display:block;font-size:20px;color:#58a6ff;}
  .stat span{font-size:11px;color:#8b949e;}
  table{border-collapse:collapse;width:100%;font-size:13px;margin-bottom:18px;}
  th{background:#161b22;color:#58a6ff;text-align:left;padding:6px 10px;border:1px solid #30363d;}
  td{padding:6px 10px;border:1px solid #30363d;}
  .alive{color:#3fb950;} .dead{color:#f85149;} .err{color:#d29922;}
  .routes{font-size:12px;color:#8b949e;}
  code{color:#79c0ff;}
</style>
</head>
<body>
<h1>Genspark Gateway — openai-compatible proxy</h1>
<div class="sub">upstream <b>www.genspark.ai</b> &middot; cookie-session pool &middot; random rotation</div>
<div class="stats">
  <div class="stat"><b id="s-acc">–</b><span>accounts</span></div>
  <div class="stat"><b id="s-alive">–</b><span>alive</span></div>
  <div class="stat"><b id="s-points">–</b><span>credits</span></div>
  <div class="stat"><b id="s-models">–</b><span>models</span></div>
</div>
<table id="tbl">
  <tr><th>email</th><th>credits</th><th>state</th></tr>
</table>
<div><b style="color:#58a6ff">models:</b> <span id="mlist" class="routes"></span></div>
<div class="routes" style="margin-top:8px" id="routes"></div>
<script>
fetch('/dash/data').then(r=>r.json()).then(d=>{
  document.getElementById('s-acc').textContent=d.accounts_total;
  document.getElementById('s-alive').textContent=d.alive;
  document.getElementById('s-points').textContent=d.points.toLocaleString();
  document.getElementById('s-models').textContent=d.models.length;
  const tbl=document.getElementById('tbl');
  d.accounts.forEach(a=>{
    const st=a.dead?'<span class="dead">dead</span>':(a.error?'<span class="err">err</span>':'<span class="alive">alive</span>');
    tbl.insertAdjacentHTML('beforeend',`<tr><td>${a.email}</td><td>${a.balance.toLocaleString()}</td><td>${st}</td></tr>`);
  });
  document.getElementById('mlist').textContent=d.models.join(' · ');
  document.getElementById('routes').innerHTML='routes: '+d.routes.map(r=>'<code>'+r+'</code>').join(' · ');
});
</script>
</body>
</html>"""


async def handle_dash(req):
    return web.Response(text=DASH_HTML, content_type="text/html")


async def handle_dash_data(req):
    return web.json_response(await dash_data())


def build_payload(messages, model):
    last_user = ""
    for m in reversed(messages):
        if m["role"] == "user":
            c = m.get("content", "")
            if isinstance(c, list):
                for item in c:
                    if item.get("type") == "text":
                        last_user = item["text"]
                        break
            elif isinstance(c, str):
                last_user = c
            break
    use_model = "auto" if model in ("auto", None) else model
    return {"user_s_input": last_user, "messages": messages, "use_model": use_model}


async def proxy_chat(req):
    if not check_auth(req):
        return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        body = await req.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    stream = body.get("stream", False)
    messages = body.get("messages", [])
    model = body.get("model", "auto")
    if not messages:
        return web.json_response({"error": "No messages"}, status=400)
    payload = build_payload(messages, model)
    if stream:
        return await handle_stream(req, payload)
    return await handle_nonstream(req, payload)


async def handle_nonstream(req, payload):
    acc = pick_account()
    async with aiohttp.ClientSession(headers=headers_for(acc["session_id"])) as sess:
        async with sess.post(f"{GENSERVER}/api/agent/ask_proxy", json=payload, timeout=aiohttp.ClientTimeout(120)) as resp:
            raw = await resp.text()
    if looks_dead(raw):
        mark_dead(acc)
        return web.json_response({"error": "account_dead", "detail": raw[:200], "account": acc["email"]}, status=401)
    content, usage, timed_out = parse_stream(raw)
    if timed_out:
        return web.json_response({
            "error": "upstream_timeout",
            "detail": content[:200],
            "account": acc["email"],
        }, status=503)
    return web.json_response({
        "id": f"gs-{time.time()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("use_model", "auto"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": usage,
        "_account": acc["email"],
    })


async def handle_stream(req, payload):
    acc = pick_account()
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(req)
    async with aiohttp.ClientSession(headers=headers_for(acc["session_id"])) as sess:
        async with sess.post(f"{GENSERVER}/api/agent/ask_proxy", json=payload, timeout=aiohttp.ClientTimeout(120)) as gs_resp:
            raw = await gs_resp.text()
    if looks_dead(raw):
        mark_dead(acc)
        await response.write(f'data: {json.dumps({"error": "account_dead", "account": acc["email"]})}\n\n'.encode())
        await response.write_eof()
        return response
    content, usage, timed_out = parse_stream(raw)
    if timed_out:
        await response.write(f'data: {json.dumps({"error": "upstream_timeout", "account": acc["email"]})}\n\n'.encode())
        await response.write_eof()
        return response
    msg_id = f"gs-{time.time()}"
    created = int(time.time())
    await response.write(
        f'data: {json.dumps({"id": msg_id, "object": "chat.completion.chunk", "created": created, "model": payload.get("use_model", "auto"), "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})}\n\n'.encode()
    )
    for block in raw.split("\n\n"):
        if not block.startswith("data: "):
            continue
        try:
            d = json.loads(block[6:])
        except Exception:
            continue
        if d.get("type") == "message_field_delta" and d.get("field_name") == "content":
            delta = d.get("delta", "")
            chunk = {
                "id": msg_id, "object": "chat.completion.chunk", "created": created,
                "model": payload.get("use_model", "auto"),
                "choices": [{"index": 0, "delta": {"content": delta}, "finish_reason": None}],
            }
            await response.write(f'data: {json.dumps(chunk)}\n\n'.encode())
    await response.write(
        f'data: {json.dumps({"id": msg_id, "object": "chat.completion.chunk", "created": created, "model": payload.get("use_model", "auto"), "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})}\n\n'.encode()
    )
    await response.write(b"data: [DONE]\n\n")
    await response.write_eof()
    return response


app = web.Application()
app.router.add_get("/", handle_dash)
app.router.add_get("/dash/data", handle_dash_data)
app.router.add_get("/v1/models", handle_models)
app.router.add_get("/v1/credit", handle_credit)
app.router.add_post("/v1/import-account", handle_import)
app.router.add_get("/v1/accounts", handle_accounts)
app.router.add_post("/v1/chat/completions", proxy_chat)
app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
