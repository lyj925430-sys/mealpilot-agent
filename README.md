# Personal Chief API

Personal Chief is a small AI cooking assistant built with FastAPI, LangChain/LangGraph checkpoint memory, an LLM, Tavily search, and Aliyun OSS.

The app accepts an ingredient list or a food image, searches for recipe ideas, and streams a practical recommendation back to the browser.

## Project Layout

```text
app/
  agents/          Single cooking agent and checkpoint memory
  api/v1/          HTTP API routes
  common/          Logging and shared helpers
  core/            Runtime settings
  models/          Request models and validation
  static/          Browser UI
database/          Local checkpoint database, generated at runtime
tests/             Smoke tests
```

`notebooks/` is only for practice notes and is not part of the production app path.

## Setup

```powershell
uv sync
Copy-Item .env.example .env
```

Fill in `.env` with the model, search, and OSS settings.

Required for chat:

- `DASHSCOPE_API_KEY`
- `BASE_URL`
- `TAVILY_API_KEY`

Required for image upload:

- `OSS_BUCKET`
- Aliyun OSS credentials in environment variables supported by the OSS SDK

## Run

```powershell
uv run python -m app.main
```

Default URL:

```text
http://127.0.0.1:8001
```

## API

- `GET /health`: health check and feature readiness.
- `POST /api/v1/chat/stream`: plain text streaming chat response.
- `GET /api/v1/chat/messages?thread_id=...`: get conversation history.
- `DELETE /api/v1/chat/messages?thread_id=...`: clear conversation history.
- `GET /api/v1/oss/presign?filename=...`: create a presigned image upload URL.

## Agent Workflow

The chat endpoint is backed by one cooking agent:

```text
User text/image
  -> Cooking agent
  -> web_search tool when recipe lookup is needed
  -> Plain text streaming answer
```

Conversation state is kept with SQLite checkpoints keyed by `thread_id`.

## Checks

```powershell
uv run python -m compileall app tests
uv run python -m unittest discover -s tests
```
