# cr-memory-bank-sample

ADK agent with [Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) integration, deployed to Cloud Run.

The agent remembers user preferences and facts across sessions using Memory Bank's managed memory topics. It uses `PreloadMemoryTool` to retrieve memories at the start of each turn and an `after_agent_callback` to trigger memory generation after each interaction. The Agent Engine instance serves as both the session backend and the Memory Bank backend.

## Project Structure

```
cr-memory-bank-sample/
├── app/
│   ├── agent.py               # Agent with memory callback + PreloadMemoryTool
│   ├── fast_api_app.py        # FastAPI server + Memory Bank config + memory_service_uri
│   └── app_utils/
│       ├── telemetry.py       # OpenTelemetry setup
│       └── typing.py          # Pydantic models
├── Makefile                   # Install, deploy, test, eval commands
├── tests/                     # Unit, integration, and eval tests
└── pyproject.toml             # Project dependencies
```

## How Memory Bank Works

When deployed to Cloud Run with an Agent Engine backend, the agent uses `VertexAiMemoryBankService`:

1. **Memory retrieval**: `PreloadMemoryTool` fetches relevant memories at the start of each turn and injects them into the system instruction.
2. **Memory generation**: `generate_memories_callback` sends session events to Memory Bank after each turn, extracting user preferences and facts.
3. **Consolidation**: Memory Bank automatically merges new memories with existing ones, avoiding duplicates and resolving contradictions.

The Memory Bank is configured with three managed topics:
- `USER_PERSONAL_INFO` — names, relationships, hobbies, important dates
- `USER_PREFERENCES` — likes, dislikes, preferred styles
- `EXPLICIT_INSTRUCTIONS` — things the user explicitly asks the agent to remember

## Changes from Base Template

This sample was scaffolded with `agents-cli create` and then modified to integrate Memory Bank. Every change is marked with `--- Memory Bank integration ---` in the source. Here is a summary:

### `app/agent.py`

| Change | What | Why |
|---|---|---|
| Import `CallbackContext` | `from google.adk.agents.callback_context import CallbackContext` | Required for the memory generation callback |
| Import `PreloadMemoryTool` | `from google.adk.tools.preload_memory_tool import PreloadMemoryTool` | Retrieves memories at the start of each turn |
| Add `generate_memories_callback` | Async callback that calls `callback_context.add_session_to_memory()` | Triggers memory generation after each agent turn |
| Add `PreloadMemoryTool()` to tools | Appended to the agent's tools list | Injects recalled memories into the system instruction |
| Set `after_agent_callback` | `after_agent_callback=generate_memories_callback` | Wires the callback to fire after each turn |
| Update instruction | Added "You remember user preferences..." | Tells the model to use recalled memories |

### `app/fast_api_app.py`

| Change | What | Why |
|---|---|---|
| Import Memory Bank types | `AgentEngineConfig`, `ManagedTopicEnum`, `MemoryBankConfig`, etc. from `vertexai._genai.types` | Class-based config for memory topics |
| Import `vertexai` | `import vertexai` | Required for `vertexai.Client` API |
| Remove `agent_engines` import | Replaced `from vertexai import agent_engines` | Switched to `vertexai.Client` API for Memory Bank support |
| Define `memory_bank_config` | `MemoryBankConfig(customization_configs=[...])` | Configures which memory topics to extract |
| Switch to `vertexai.Client` API | `client = vertexai.Client(...)` with `client.agent_engines.list/create` | Old `agent_engines` module-level API doesn't support `context_spec` |
| Create Agent Engine with `context_spec` | `AgentEngineConfig(display_name=..., context_spec=...)` | New instances are created with Memory Bank enabled |
| Add `memory_service_uri` | Set to same `agentengine://` URI as `session_service_uri` | Tells ADK to use `VertexAiMemoryBankService` for memory operations |
| Pass `memory_service_uri` to `get_fast_api_app()` | `memory_service_uri=memory_service_uri` | Wires Memory Bank into the FastAPI server |

### `tests/integration/test_agent.py`

| Change | What | Why |
|---|---|---|
| Import `InMemoryMemoryService` | `from google.adk.memory import InMemoryMemoryService` | In-memory memory backend for tests |
| Import `PreloadMemoryTool` | `from google.adk.tools.preload_memory_tool import PreloadMemoryTool` | Used to verify agent wiring |
| Import `generate_memories_callback` | `from app.agent import generate_memories_callback` | Used to verify agent wiring |
| Add `test_agent_has_memory_wired()` | Checks callback and PreloadMemoryTool are set | Catches regressions if memory integration is accidentally removed |
| Add `InMemoryMemoryService` to runner | `memory_service=InMemoryMemoryService()` | Prevents test failures from missing memory service |

## Requirements

Before you begin, ensure you have:
- **uv**: Python package manager - [Install](https://docs.astral.sh/uv/getting-started/installation/)
- **Google Cloud SDK**: For GCP services - [Install](https://cloud.google.com/sdk/docs/install)

## Quick Start

```bash
make install        # Install dependencies
make playground     # Launch local dev playground (ADK Web UI on port 8501)
```

## Commands

| Command | Description |
|---|---|
| `make install` | Install dependencies using uv |
| `make playground` | Launch local dev playground |
| `make deploy` | Deploy to Cloud Run with Memory Bank enabled |
| `make test` | Run unit and integration tests |
| `make eval` | Run agent evaluation |
| `make lint` | Run code quality checks |

## Deployment

Deploy to Cloud Run with Memory Bank enabled:

```bash
gcloud config set project <your-project-id>
make deploy
```

On first startup, the Cloud Run service will:
1. Find or create an Agent Engine instance (using `AGENT_ENGINE_SESSION_NAME`)
2. If creating, pass `memory_bank_config` via `context_spec` to enable Memory Bank
3. Set `session_service_uri` and `memory_service_uri` to the same `agentengine://` URI
4. Start the FastAPI server with both session and memory services wired up

## Development

Edit your agent logic in `app/agent.py` and test with `make playground` — it auto-reloads on save.

When running locally, ADK uses `InMemoryMemoryService` by default. To test against a real Memory Bank instance locally, use:

```bash
uv run adk web . --port 8501 --memory_service_uri=agentengine://<AGENT_ENGINE_RESOURCE_NAME>
```

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.
