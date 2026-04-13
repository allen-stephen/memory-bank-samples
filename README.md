# ADK Memory Bank Samples

Two reference implementations of an ADK agent with [Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) integration, deployed to Google Cloud using [ADK](https://adk.dev/) and the [Agents CLI](https://pypi.org/project/google-agents-cli/).

Both agents do the same thing — answer weather and time queries while remembering user preferences and facts across sessions — but use different deployment targets and infrastructure.

| | `ae-memory-bank-sample` | `cr-memory-bank-sample` |
|---|---|---|
| **Deployment target** | Vertex AI Agent Engine | Cloud Run (FastAPI) |
| **Entry point** | `AgentEngineApp` | `FastAPI` via `get_fast_api_app()` |
| **Session management** | Agent Engine (managed) | Agent Engine (remote, via `agentengine://` URI) |
| **Memory Bank config** | `context_spec` in `AgentEngineConfig` (via `deploy.py`) | `context_spec` in `AgentEngineConfig` (at server startup) |
| **Memory service** | `VertexAiMemoryBankService` (automatic) | `VertexAiMemoryBankService` (via `memory_service_uri`) |
| **Memory retrieval** | `PreloadMemoryTool` | `PreloadMemoryTool` |
| **Memory generation** | `after_agent_callback` | `after_agent_callback` |
| **Container** | Managed by Agent Engine | Dockerfile + `uvicorn` |
| **Deploy command** | `make deploy` | `make deploy` |

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

## How Memory Bank Works

Both samples integrate Memory Bank using the same agent-level pattern, with differences only in how the Memory Bank service is configured for each deployment target.

### Agent-level (shared)

1. **`PreloadMemoryTool`** retrieves relevant memories at the start of each turn and injects them into the system instruction. The model sees past user preferences and facts as context without needing an explicit tool call.
2. **`generate_memories_callback`** fires after each agent turn via `after_agent_callback`, calling `callback_context.add_session_to_memory()` to send the session's events to Memory Bank for memory extraction.
3. **Memory Bank** automatically consolidates new memories with existing ones, avoiding duplicates and resolving contradictions.

### Platform-level (differs by target)

**Agent Engine**: `AdkApp` automatically uses `VertexAiMemoryBankService` when deployed with a `memory_bank_config` in `context_spec`. The deploy script (`app/app_utils/deploy.py`) passes the config via `AgentEngineConfig`.

**Cloud Run**: The FastAPI server (`app/fast_api_app.py`) creates or finds an Agent Engine instance with `memory_bank_config` at startup, then passes the `agentengine://` URI as `memory_service_uri` to `get_fast_api_app()`. This tells ADK to use `VertexAiMemoryBankService` backed by that Agent Engine instance.

### Memory topics

Both samples configure three managed topics:
- `USER_PERSONAL_INFO` — names, relationships, hobbies, important dates
- `USER_PREFERENCES` — likes, dislikes, preferred styles
- `EXPLICIT_INSTRUCTIONS` — things the user explicitly asks the agent to remember

## Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- `uv` — Python package manager ([Install](https://docs.astral.sh/uv/getting-started/installation/))

## Quick Start

See each project's README for setup and deployment instructions:
- [`ae-memory-bank-sample/README.md`](ae-memory-bank-sample/README.md) — Agent Engine deployment
- [`cr-memory-bank-sample/README.md`](cr-memory-bank-sample/README.md) — Cloud Run deployment

## Agent Guide

See [`AGENT_GUIDE.md`](AGENT_GUIDE.md) for a reference on ADK concepts, Memory Bank integration patterns, deployment mechanics, session management, testing, and debugging strategies covered by these samples.
