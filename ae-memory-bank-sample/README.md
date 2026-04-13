# ae-memory-bank-sample

ADK agent with [Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) integration, deployed to Vertex AI Agent Engine.

The agent remembers user preferences and facts across sessions using Memory Bank's managed memory topics. It uses `PreloadMemoryTool` to retrieve memories at the start of each turn and an `after_agent_callback` to trigger memory generation after each interaction.

## Project Structure

```
ae-memory-bank-sample/
├── app/
│   ├── agent.py               # Agent with memory callback + PreloadMemoryTool
│   ├── agent_engine_app.py    # Agent Engine app + Memory Bank config
│   └── app_utils/
│       ├── deploy.py          # Deployment script (wires memory_bank_config)
│       ├── telemetry.py       # OpenTelemetry setup
│       └── typing.py          # Pydantic models
├── Makefile                   # Install, deploy, test, eval commands
├── tests/                     # Unit, integration, and eval tests
└── pyproject.toml             # Project dependencies
```

## How Memory Bank Works

When deployed to Agent Engine, `AdkApp` automatically uses `VertexAiMemoryBankService`:

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

### `app/agent_engine_app.py`

| Change | What | Why |
|---|---|---|
| Import Memory Bank types | `ManagedTopicEnum`, `MemoryBankConfig`, etc. from `vertexai._genai.types` | Class-based config for memory topics |
| Define `memory_bank_config` | `MemoryBankConfig(customization_configs=[...])` | Configures which memory topics to extract; exported for use by `deploy.py` |

### `app/app_utils/deploy.py`

| Change | What | Why |
|---|---|---|
| Import `ReasoningEngineContextSpec` | From `vertexai._genai.types` | Wraps the Memory Bank config for `AgentEngineConfig` |
| Import `memory_bank_config` | From `app.agent_engine_app` | Reads the config defined alongside the agent |
| Create `context_spec` | `ReasoningEngineContextSpec(memory_bank_config=memory_bank_config)` | Wraps the config for the deployment API |
| Pass `context_spec` to `AgentEngineConfig` | `context_spec=context_spec` | Agent Engine instance is created with Memory Bank enabled |

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
| `make deploy` | Deploy to Agent Engine with Memory Bank enabled |
| `make test` | Run unit and integration tests |
| `make eval` | Run agent evaluation |
| `make lint` | Run code quality checks |

## Deployment

Deploy to Agent Engine with Memory Bank enabled:

```bash
gcloud config set project <your-project-id>
make deploy
```

The `make deploy` target runs `app/app_utils/deploy.py`, which:
1. Reads `memory_bank_config` from `agent_engine_app.py`
2. Wraps it in a `ReasoningEngineContextSpec`
3. Passes it via `context_spec` in the `AgentEngineConfig`
4. Creates or updates the Agent Engine instance with Memory Bank configured

## Development

Edit your agent logic in `app/agent.py` and test with `make playground` — it auto-reloads on save.

When running locally, ADK uses `InMemoryMemoryService` by default. To test against a real Memory Bank instance locally, use:

```bash
uv run adk web . --port 8501 --memory_service_uri=agentengine://<AGENT_ENGINE_ID>
```

## Observability

Built-in telemetry exports to Cloud Trace, BigQuery, and Cloud Logging.
