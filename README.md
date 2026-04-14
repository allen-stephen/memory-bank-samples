# ADK Memory Bank Sample

An [ADK](https://adk.dev/) agent with [Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) integration that remembers user preferences and facts across sessions. Deployable to Vertex AI Agent Engine or Cloud Run.

<table>
  <thead>
    <tr>
      <th colspan="2">Key Features</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Cross-session memory</strong></td>
      <td>Remembers user preferences, personal info, and explicit instructions across conversations using Memory Bank's managed topics.</td>
    </tr>
    <tr>
      <td><strong>Automatic memory extraction</strong></td>
      <td>An <code>after_agent_callback</code> sends session events to Memory Bank after each turn — no manual tagging needed.</td>
    </tr>
    <tr>
      <td><strong>Preloaded recall</strong></td>
      <td><code>PreloadMemoryTool</code> injects relevant memories into the system instruction at the start of each turn, so the model sees them automatically.</td>
    </tr>
    <tr>
      <td><strong>Two deployment targets</strong></td>
      <td>Same agent code, deployable to Agent Engine (fully managed) or Cloud Run (container-based with FastAPI).</td>
    </tr>
  </tbody>
</table>

## Example Interactions

Memory Bank shines in multi-session conversations. Here are some examples showing how memories are saved and recalled:

**Session 1** — tell the agent about yourself:
```
You: I live in Austin, Texas.
Agent: Got it! Austin is a great city — known for its live music scene and BBQ. Let me know if you need anything Austin-related!
```

**Session 2** — the agent remembers without being reminded:
```
You: What's the weather like?
Agent: Here's the current weather for Austin, Texas: It's 90 degrees and sunny.
```

**Session 1** — set a preference:
```
You: I want you to talk like a pirate from now on.
Agent: Aye aye, captain! Consider it done — I'll be speakin' in the tongue of the seven seas from here on out! What be yer next command?
```

**Session 2** — the preference persists:
```
You: What can you help me with?
Agent: Ahoy, matey! I can help ye with weather reports, tellin' the time, and rememberin' all manner of facts about ye. What treasure of knowledge be ye seekin' today?
```

These work because:
- `PreloadMemoryTool` retrieves "lives in Austin" and "wants pirate speak" at the start of each turn
- `generate_memories_callback` extracts those facts after the first session
- Memory Bank consolidates them so they're available in every future session

## Getting Started

### Prerequisites
- **Python 3.10+**
- **uv** — Python package manager ([Install](https://docs.astral.sh/uv/getting-started/installation/))
- **Google Cloud SDK** — `gcloud` CLI ([Install](https://cloud.google.com/sdk/docs/install))
- Google Cloud project with billing enabled

### Step 1: Install Dependencies
```bash
make install
```

### Step 2: Authenticate with Google Cloud
```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project <your-project-id>
```

### Step 3: Run Locally
```bash
make playground
```
This launches the ADK Web UI on port 8501. Select the `app` folder to interact with your agent.

When running locally, ADK uses `InMemoryMemoryService` — memories won't persist across restarts. To test against a real Memory Bank instance:
```bash
uv run adk web . --port 8501 --memory_service_uri=agentengine://<AGENT_ENGINE_RESOURCE_NAME>
```

## Cloud Deployment Options

After completing the initial setup, you have two deployment options:

### Option A: Deploy to Vertex AI Agent Engine

Agent Engine provides fully managed infrastructure — session management, memory, and scaling are handled automatically.

```bash
make deploy-agent-engine
```

This runs `app/app_utils/deploy.py`, which:
1. Reads `memory_bank_config` from `agent_engine_app.py`
2. Wraps it in a `ReasoningEngineContextSpec`
3. Passes it via `context_spec` in the `AgentEngineConfig`
4. Creates or updates the Agent Engine instance with Memory Bank configured

Entry point: `app/agent_engine_app.py` (`AgentEngineApp`, a subclass of `AdkApp`)

### Option B: Deploy to Cloud Run

Cloud Run gives you full control over the serving infrastructure — custom endpoints, middleware, container environment.

```bash
make deploy-cloud-run
```

On first startup, the Cloud Run service will:
1. Find or create an Agent Engine instance for session and memory storage
2. If creating, pass `memory_bank_config` via `context_spec` to enable Memory Bank
3. Set `session_service_uri` and `memory_service_uri` to the same `agentengine://` URI
4. Start the FastAPI server with both services wired up

Entry point: `app/fast_api_app.py` (FastAPI via `get_fast_api_app()`)

## Project Structure

```
memory-bank-sample/
├── app/
│   ├── agent.py                # Shared agent definition (tools, memory callback, PreloadMemoryTool)
│   ├── agent_engine_app.py     # Agent Engine entry point + Memory Bank config
│   ├── fast_api_app.py         # Cloud Run entry point + Memory Bank config
│   └── app_utils/
│       ├── deploy.py           # Agent Engine deployment script
│       ├── telemetry.py        # OpenTelemetry setup
│       └── typing.py           # Pydantic models
├── tests/                      # Unit, integration, and eval tests
├── Dockerfile                  # Cloud Run container
├── Makefile                    # Install, deploy, test, eval commands
└── pyproject.toml              # Project dependencies
```

## How Memory Bank Works

### Agent-level (shared across both deployment targets)

1. **`PreloadMemoryTool`** retrieves relevant memories at the start of each turn and injects them into the system instruction. The model sees past user preferences and facts as context without needing an explicit tool call.
2. **`generate_memories_callback`** fires after each agent turn via `after_agent_callback`, calling `callback_context.add_session_to_memory()` to send the session's events to Memory Bank for memory extraction.
3. **Memory Bank** automatically consolidates new memories with existing ones, avoiding duplicates and resolving contradictions.

### Platform-level (differs by deployment target)

**Agent Engine**: `AdkApp` automatically uses `VertexAiMemoryBankService` when deployed with a `memory_bank_config` in `context_spec`. The deploy script (`app/app_utils/deploy.py`) passes the config via `AgentEngineConfig`.

**Cloud Run**: The FastAPI server (`app/fast_api_app.py`) creates or finds an Agent Engine instance with `memory_bank_config` at startup, then passes the `agentengine://` URI as `memory_service_uri` to `get_fast_api_app()`. This tells ADK to use `VertexAiMemoryBankService` backed by that Agent Engine instance.

### Memory topics

Both entry points configure three managed topics:
- `USER_PERSONAL_INFO` — names, relationships, hobbies, important dates
- `USER_PREFERENCES` — likes, dislikes, preferred styles
- `EXPLICIT_INSTRUCTIONS` — things the user explicitly asks the agent to remember

## Commands

| Command | Description |
|---|---|
| `make install` | Install dependencies using uv |
| `make playground` | Launch local dev playground (ADK Web UI) |
| `make deploy-agent-engine` | Deploy to Vertex AI Agent Engine |
| `make deploy-cloud-run` | Deploy to Cloud Run |
| `make local-server` | Run FastAPI server locally with hot-reload |
| `make test` | Run unit and integration tests |
| `make eval` | Run agent evaluation |
| `make lint` | Run code quality checks |

## Agent Guide

See [`AGENT_GUIDE.md`](AGENT_GUIDE.md) for a deeper reference on ADK concepts, Memory Bank integration patterns, deployment mechanics, session management, testing, and debugging strategies.

## Disclaimer

This software is provided as-is, without warranty or representation for any use or purpose. This is sample code intended for demonstration and learning purposes only. It is not intended for production use. Your use of this software is at your own risk.
