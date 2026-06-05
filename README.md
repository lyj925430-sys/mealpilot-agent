# Personal Chief API

Personal Chief is a small AI cooking assistant built with FastAPI, LangChain/LangGraph checkpoint memory, an LLM, Tavily search, Aliyun OSS, and a kitchen-memory meal planning layer.

The app accepts an ingredient list or a food image, searches for recipe ideas, and streams a practical recommendation back to the browser. It also stores a user's kitchen inventory and preferences, then generates multi-day meal plans that prioritize expiring ingredients and produce a shopping list.

## Project Layout

```text
app/
  agents/          Single cooking agent and checkpoint memory
  api/v1/          HTTP API routes
  common/          Logging and shared helpers
  core/            Runtime settings
  models/          Request models and validation
  services/        Kitchen memory and meal planning service
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
- `POST /api/v1/auth/register`: create a local user and return a bearer token.
- `POST /api/v1/auth/login`: verify username/password and return a bearer token.
- `GET /api/v1/auth/me`: get the current user from the bearer token.
- `POST /api/v1/auth/logout`: revoke the current bearer token.
- `GET /api/v1/auth/household`: get the current user's health and household meal profile.
- `PUT /api/v1/auth/household`: save health indicators and relatives' dietary constraints.
- `POST /api/v1/chat/stream`: plain text streaming chat response.
- `GET /api/v1/chat/messages?thread_id=...`: get conversation history.
- `DELETE /api/v1/chat/messages?thread_id=...`: clear conversation history.
- `GET /api/v1/oss/presign?filename=...`: create a presigned image upload URL.
- `GET /api/v1/chef/inventory?thread_id=...`: get saved kitchen inventory.
- `POST /api/v1/chef/inventory`: upsert inventory items with quantity, category, and expiry date.
- `DELETE /api/v1/chef/inventory?thread_id=...`: clear saved inventory.
- `POST /api/v1/chef/inventory/consume`: record consumed ingredients after cooking.
- `GET /api/v1/chef/preferences?thread_id=...`: get saved cooking preferences.
- `POST /api/v1/chef/preferences`: save goals, allergies, disliked ingredients, flavors, budget, and cooking time.
- `POST /api/v1/chef/meal-plan`: generate a 1-7 day meal plan from inventory and preferences.
- `POST /api/v1/chef/substitutions`: suggest substitutes for missing ingredients using inventory and preferences.
- `POST /api/v1/chef/nutrition`: estimate lightweight calories and macros for meal planning.
- `POST /api/v1/chef/cooking-session`: start step-by-step cooking guidance.
- `GET /api/v1/chef/cooking-session?thread_id=...`: get the current cooking step.
- `POST /api/v1/chef/cooking-session/advance`: move to next, previous, current, or finished step.

## Agent Workflow

The chat endpoint is backed by one cooking agent:

```text
User text/image
  -> Cooking agent
  -> kitchen memory context by thread_id
  -> web_search tool when recipe lookup is needed
  -> meal_plan tool when multi-day planning is needed
  -> inventory/substitution/nutrition/cooking-step tools during execution
  -> Plain text streaming answer
```

Conversation state is kept with SQLite checkpoints keyed by `thread_id`.
Kitchen inventory and user preferences are stored in a separate SQLite database, also keyed by `thread_id`.

## Agent Upgrade Highlight

The resume-worthy upgrade is a kitchen-memory planning agent:

- Tracks ingredients, quantity, category, notes, and expiry date.
- Adds local username/password auth with salted PBKDF2 password hashes and bearer tokens.
- Stores user health indicators and relatives' dining constraints, then injects them into the Agent context for more personalized planning.
- Stores long-term preferences such as allergies, disliked ingredients, budget, and cooking time.
- Generates multi-day menus with an anti-waste strategy that prioritizes expiring ingredients.
- Produces optional shopping suggestions while keeping the main dishes cookable from existing inventory.
- Adds execution tools for inventory updates, inventory consumption, ingredient substitutions, lightweight nutrition estimates, and cooking-step tracking.
- Injects the saved kitchen memory into the LangGraph-backed chat flow, so the agent can make context-aware recommendations and update the meal workflow.

Example meal-plan request:

```json
{
  "thread_id": "demo-user",
  "days": 3,
  "meals": ["dinner"],
  "people": 1
}
```

## Checks

```powershell
uv run python -m compileall app tests
uv run python -m unittest discover -s tests
```
