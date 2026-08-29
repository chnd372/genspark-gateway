# Genspark Gateway

OpenAI-compatible proxy for [Genspark.ai](https://www.genspark.ai) — turns a logged-in Genspark account (with credits) into an `/v1/chat/completions` API. Supports **multi-account pool** with random rotation, dead-account detection, and a live dashboard.

> ⚠️ Genspark has **no public API**. This gateway reverse-engineers the internal `ask_proxy` SSE endpoint used by the Genspark web UI. Use at your own risk.

## Features

- ✅ OpenAI-compatible `/v1/chat/completions` (stream + non-stream)
- ✅ 57 models (GPT-5.x, Claude Opus/Sonnet, Gemini 3.x, GLM-5.2, DeepSeek V4, Grok-4.x, Kimi, Qwen, Minimax, ...)
- ✅ Multi-account pool with **random rotation** (spread load, avoid bans)
- ✅ Auto dead-account detection (expired session → skipped)
- ✅ Upstream timeout detection → HTTP 503 (account NOT marked dead)
- ✅ Live dashboard at `/`
- ✅ Account import via API (`POST /v1/import-account`)
- ✅ Credit balance aggregator (`GET /v1/credit`)
- ✅ Works behind Cloudflare Tunnel / any reverse proxy

## Architecture

```
Client (OpenAI SDK / 9router / any)
        │  POST /v1/chat/completions
        ▼
  gateway.py  (aiohttp, :20132)
        │  random account pick
        ▼
  POST https://www.genspark.ai/api/agent/ask_proxy
        │  SSE stream
        ▼
  parsed → OpenAI chat.completion (or stream chunks)
```

The real model is selected via the `use_model` field (not `model`). The gateway maps your OpenAI request `model` name 1:1 to Genspark's internal model ids.

## Requirements

- Python 3.10+
- `pip install aiohttp`

## Install

```bash
git clone https://github.com/chnd372/genspark-gateway.git
cd genspark-gateway
pip install aiohttp
```

## Get your Genspark session cookie

1. Log in to https://www.genspark.ai
2. Open DevTools → **Application** → **Cookies** → `www.genspark.ai`
3. Copy the value of the **`session_id`** cookie (looks like `15515a7f-....:hash....`)
4. The gateway appends `; gslogin=1` automatically if missing

> The session cookie is valid for ~30 days. It does **not** auto-refresh; re-login when it expires.

## Quick Start

### Single account

```bash
export GS_SESSION="session_id=PASTE-YOUR-SESSION-ID-HERE; gslogin=1"
export GS_API_KEY="sk-gs-your-secret-key"

python3 gateway.py
```

Gateway starts on port 20132.

### Multi-account pool

Option A — drop JSON files into `ACCOUNTS_DIR` (default `/opt/data/gs_accounts`):

```bash
mkdir -p /opt/data/gs_accounts
cat > /opt/data/gs_accounts/acc1.json <<'EOF'
{"email": "user1@gmail.com", "session_id": "session_id=AAA...; gslogin=1", "dead": false}
EOF
```

Option B — import via API:

```bash
curl -X POST http://localhost:20132/v1/import-account \
  -H "Authorization: Bearer sk-gs-your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "session_id=CCC...; gslogin=1", "email": "user3@gmail.com"}'
```

Then run `python3 gateway.py` — all accounts rotate randomly per request.

## Usage

### Chat completion

```bash
curl http://localhost:20132/v1/chat/completions \
  -H "Authorization: Bearer sk-gs-your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "glm-5p2",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### Streaming

```bash
curl -N http://localhost:20132/v1/chat/completions \
  -H "Authorization: Bearer sk-gs-your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-opus-5",
    "stream": true,
    "messages": [{"role": "user", "content": "Write a haiku"}]
  }'
```

### List models

```bash
curl http://localhost:20132/v1/models \
  -H "Authorization: Bearer sk-gs-your-secret-key"
```

### Check credit balance (all accounts)

```bash
curl http://localhost:20132/v1/credit \
  -H "Authorization: Bearer sk-gs-your-secret-key"
```

### Dashboard

Open `http://localhost:20132/` in a browser — live stats, account list, model catalog.

## API Reference

| Method | Route | Auth | Description |
|--------|-------|------|-------------|
| `GET` | `/` | no | Dashboard HTML |
| `GET` | `/health` | no | Health check |
| `GET` | `/v1/models` | Bearer | List 57 models |
| `POST` | `/v1/chat/completions` | Bearer | Chat (stream + non-stream) |
| `GET` | `/v1/credit` | Bearer | Total + per-account balance |
| `GET` | `/v1/accounts` | Bearer | List accounts in pool |
| `POST` | `/v1/import-account` | Bearer | Add account from session cookie |

## Available Models

| Category | Model ids |
|----------|-----------|
| Auto | `auto` |
| OpenAI | `gpt-5-pro`, `gpt-5.1-low`, `gpt-5.1-medium`, `gpt-5.1-high`, `gpt-5.2`, `gpt-5.2-pro`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.4-nano`, `gpt-5.4-pro`, `gpt-5.5`, `gpt-5.5-pro`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `o3-pro` |
| Anthropic | `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-opus-4-6`, `claude-opus-4-5`, `claude-opus-4-1`, `claude-sonnet-5`, `claude-sonnet-4-6`, `claude-sonnet-4-5`, `claude-sonnet-4`, `claude-4-5-haiku` |
| Google | `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite-preview`, `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.7-flash`, `gemini-2.5-pro`, `gemini-2.5-flash` |
| DeepSeek | `deep-seek-v4-pro`, `deep-seek-v4-flash`, `deepseek-v4-pro-0813` |
| Zhipu | `glm-5p2` (GLM-5.2), `glm-5p3-openrouter` (GLM-5.3), `glm-5p3-flash-baseten` |
| Moonshot | `kimi-k3`, `kimi-k2p6`, `kimi-k2-instruct`, `groq-kimi-k2-instruct` |
| xAI | `grok-4.5`, `grok-4.6`, `grok-4-0709`, `grok-4.20-0309-reasoning`, `grok-4.20-0309-non-reasoning` |
| MiniMax | `minimax-m3`, `minimax-m2p7` |
| Other | `qwen-3.8-max`, `solar-pro4`, `nemotron-3-ultra`, `trinity-large-thinking` |

## Response Format

OpenAI-compatible, plus a `_account` field showing which Genspark account served the request:

```json
{
  "id": "gs-1787984336.519",
  "object": "chat.completion",
  "created": 1787984336,
  "model": "glm-5p2",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "Hello!"},
    "finish_reason": "stop"
  }],
  "usage": {"prompt_tokens": 33497, "completion_tokens": 5, "total_tokens": 33526},
  "_account": "user1@gmail.com"
}
```

## Exposing publicly (Cloudflare Tunnel)

```bash
cloudflared tunnel --url http://localhost:20132
```

Copy the `https://....trycloudflare.com` URL — use it as base URL in OpenAI SDK / 9router / OneAPI / LobeChat etc:

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://YOUR-TUNNEL.trycloudflare.com/v1",
    api_key="sk-gs-yo**-key",
)
resp = client.chat.completions.create(
    model="glm-5p2",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

## Configuration (env vars)

| Var | Default | Description |
|-----|---------|-------------|
| `GS_SESSION` | `""` | Fallback single session cookie |
| `GS_API_KEY` | `sk-gs-CHANGE-ME` | Bearer key clients must send |
| `PORT` | `20132` | Listen port |
| `ACCOUNTS_DIR` | `/opt/data/gs_accounts` | Pool directory (edit in gateway.py) |

## How it works (reverse-engineering notes)

- Chat endpoint: `POST https://www.genspark.ai/api/agent/ask_proxy`
- Payload: `{"user_s_input": "...", "messages": [...], "use_model": "glm-5p2"}`
- Response: SSE stream (`data: {...}` events)
  - `message_field_delta` → incremental content
  - `message_field` → final content
  - `message_result` → includes `session_state._llm_usage` (token counts)
- Credit balance: `GET /api/payment/get_credit_balance`
- Login check: `GET /api/is_login`
- Model catalog: extracted from the `_nuxt` JS bundle (`name:"..."` entries)
- Auth: `session_id` cookie only (no JWT refresh flow)

## Limitations

- No conversation continuity — each request creates a new Genspark project
- `system` messages are passed through but Genspark's agent may rephrase
- Heavy prompts burn credits fast (agent overhead ~33K prompt tokens per call)
- Session expires ~30 days → re-login + re-import
- ToS: automating Genspark may violate their terms; account could be banned

## License

MIT
