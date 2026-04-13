# Agent Guide: ADK Agents on Agent Engine vs Cloud Run

Practical learnings from building and deploying ADK agents with [Memory Bank](https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up) to two deployment targets — Vertex AI Agent Engine and Cloud Run (FastAPI) — using the [Agents CLI](https://pypi.org/project/google-agents-cli/). These supplement the official documentation with implementation details discovered while building these samples.

This guide covers both projects in this repo:
- **`ae-memory-bank-sample`** — Agent Engine deployment
- **`cr-memory-bank-sample`** — Cloud Run deployment with FastAPI

---

## 1. ADK Internals

### 1.1. `App` vs `AgentEngineApp` — choose by deployment target

| Target | Entry point class | Base class | Module |
|---|---|---|---|
| Cloud Run | `FastAPI` via `get_fast_api_app()` | `google.adk.cli.fast_api` | `google.adk.cli.fast_api` |
| Agent Engine | `AgentEngineApp` (custom subclass) | `vertexai.agent_engines.templates.adk.AdkApp` | `vertexai.agent_engines.templates.adk` |

On Cloud Run, ADK's `get_fast_api_app()` creates a FastAPI application that serves the agent. On Agent Engine, `AgentEngineApp` wraps `App` and adds telemetry, logging, feedback collection, and `register_operations()` for custom methods.

### 1.2. `AgentEngineApp` deployment pattern

```python
from vertexai.agent_engines.templates.adk import AdkApp

class AgentEngineApp(AdkApp):
    def set_up(self) -> None:
        vertexai.init()
        setup_telemetry()
        super().set_up()

    def register_operations(self) -> dict[str, list[str]]:
        operations = super().register_operations()
        operations[""] = operations.get("", []) + ["register_feedback"]
        return operations

agent_engine = AgentEngineApp(
    app=adk_app,
    artifact_service_builder=lambda: (
        GcsArtifactService(bucket_name=logs_bucket_name)
        if logs_bucket_name
        else InMemoryArtifactService()
    ),
)
```

Custom methods are exposed to Agent Engine via `register_operations()`. The entrypoint for deployment is `app.agent_engine_app:agent_engine`.

### 1.3. Cloud Run uses `get_fast_api_app()` for serving

```python
from google.adk.cli.fast_api import get_fast_api_app

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    memory_service_uri=memory_service_uri,  # Memory Bank
    otel_to_cloud=True,
)
```

This creates a FastAPI app that serves the ADK agent with a web UI, artifact storage, session management, and memory service. Custom endpoints (like `/feedback`) can be added directly to the FastAPI app.

### 1.4. Agent definition is shared across deployment targets

Both samples use the same `app/agent.py` structure:

```python
root_agent = Agent(
    name="root_agent",
    model=Gemini(model="gemini-3-flash-preview", ...),
    instruction="...You remember user preferences and facts...",
    tools=[get_weather, get_current_time, PreloadMemoryTool()],
    after_agent_callback=generate_memories_callback,
)

app = App(root_agent=root_agent, name="app")
```

The `App` instance is imported by the deployment-specific entry point (`agent_engine_app.py` or `fast_api_app.py`). This separation keeps agent logic decoupled from infrastructure.

---

## 2. Session Management

### 2.1. Agent Engine manages sessions automatically

When deployed to Agent Engine, session management is handled by the platform. No session URI configuration is needed — Agent Engine creates and manages sessions internally.

### 2.2. Cloud Run uses Agent Engine for remote sessions

The Cloud Run sample uses Agent Engine as a remote session and memory service via the `agentengine://` URI scheme. It uses the `vertexai.Client` API (rather than the module-level `agent_engines` API) so it can pass `AgentEngineConfig` with `context_spec` when creating a new instance:

```python
client = vertexai.Client(project=project_id, location=agent_engine_location)

existing_agents = list(client.agent_engines.list())
matching_agents = [
    a for a in existing_agents
    if a.api_resource.display_name == agent_name
]

if matching_agents:
    agent_engine = matching_agents[0]
else:
    context_spec = ReasoningEngineContextSpec(
        memory_bank_config=memory_bank_config,
    )
    agent_engine = client.agent_engines.create(
        config=AgentEngineConfig(
            display_name=agent_name,
            context_spec=context_spec,
        ),
    )

session_service_uri = f"agentengine://{agent_engine.api_resource.name}"
memory_service_uri = session_service_uri
```

This creates or reuses an Agent Engine resource for both session storage and Memory Bank. The agent itself runs on Cloud Run, but conversations and memories persist in Agent Engine.

### 2.3. In-memory sessions for testing

Set `USE_IN_MEMORY_SESSION=true` to skip Agent Engine session setup during local development or E2E tests. This avoids needing GCP credentials for quick iteration:

```python
if use_in_memory_session:
    session_service_uri = None   # falls back to in-memory
    memory_service_uri = None    # falls back to in-memory
```

---

## 3. Memory Bank

### 3.1. Agent-level integration

Both samples wire Memory Bank into the agent with three additions to `app/agent.py`:

1. **`PreloadMemoryTool()`** — added to the agent's `tools` list. Retrieves memories at the start of each turn and injects them into the system instruction. The model sees past user preferences and facts as context without needing an explicit tool call.

2. **`generate_memories_callback`** — an async function that calls `callback_context.add_session_to_memory()`. This sends the session's events to Memory Bank for memory extraction.

3. **`after_agent_callback=generate_memories_callback`** — wires the callback to fire after each agent turn.

```python
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None

root_agent = Agent(
    ...,
    tools=[get_weather, get_current_time, PreloadMemoryTool()],
    after_agent_callback=generate_memories_callback,
)
```

**Alternative tools**: `LoadMemoryTool()` lets the model call memory retrieval on-demand (more control, less consistency). `callback_context.add_events_to_memory(events=...)` sends only a subset of events (better for incremental processing).

### 3.2. Memory Bank configuration

Both samples configure the same three managed topics using the class-based API from `vertexai._genai.types`:

```python
from vertexai._genai.types import (
    ManagedTopicEnum,
    MemoryBankCustomizationConfig as CustomizationConfig,
    MemoryBankCustomizationConfigMemoryTopic as MemoryTopic,
    MemoryBankCustomizationConfigMemoryTopicManagedMemoryTopic as ManagedMemoryTopic,
    ReasoningEngineContextSpecMemoryBankConfig as MemoryBankConfig,
)

memory_bank_config = MemoryBankConfig(
    customization_configs=[
        CustomizationConfig(
            memory_topics=[
                MemoryTopic(managed_memory_topic=ManagedMemoryTopic(
                    managed_topic_enum=ManagedTopicEnum.USER_PERSONAL_INFO)),
                MemoryTopic(managed_memory_topic=ManagedMemoryTopic(
                    managed_topic_enum=ManagedTopicEnum.USER_PREFERENCES)),
                MemoryTopic(managed_memory_topic=ManagedMemoryTopic(
                    managed_topic_enum=ManagedTopicEnum.EXPLICIT_INSTRUCTIONS)),
            ],
        ),
    ],
)
```

Available managed topics: `USER_PERSONAL_INFO`, `USER_PREFERENCES`, `KEY_CONVERSATION_DETAILS`, `EXPLICIT_INSTRUCTIONS`. You can also define custom topics with `CustomMemoryTopic(label=..., description=...)`.

### 3.3. Import path for Memory Bank types

Memory Bank types live at `vertexai._genai.types`, **not** `vertexai.types` (which does not exist as of `google-cloud-aiplatform` v1.145.0). The long class names are aliased on import for readability.

### 3.4. Platform-level wiring differs by target

**Agent Engine** (`agent_engine_app.py` + `deploy.py`): The `memory_bank_config` is defined in `agent_engine_app.py` and imported by `deploy.py`, which wraps it in a `ReasoningEngineContextSpec` and passes it via `context_spec` in `AgentEngineConfig`. At runtime, `AdkApp` automatically uses `VertexAiMemoryBankService`.

```python
from vertexai._genai.types import ReasoningEngineContextSpec

context_spec = ReasoningEngineContextSpec(memory_bank_config=memory_bank_config)
config = AgentEngineConfig(..., context_spec=context_spec)
```

**Cloud Run** (`fast_api_app.py`): The `memory_bank_config` is defined in `fast_api_app.py` and used when creating the Agent Engine instance at server startup. The resulting `agentengine://` URI is passed as `memory_service_uri` to `get_fast_api_app()`, which tells ADK to use `VertexAiMemoryBankService`.

```python
memory_service_uri = f"agentengine://{agent_engine.api_resource.name}"

app = get_fast_api_app(..., memory_service_uri=memory_service_uri)
```

### 3.5. Testing with `InMemoryMemoryService`

For integration tests, use `InMemoryMemoryService` to avoid needing a real Memory Bank backend:

```python
from google.adk.memory import InMemoryMemoryService

runner = Runner(
    agent=root_agent,
    session_service=InMemorySessionService(),
    memory_service=InMemoryMemoryService(),
    app_name="test",
)
```

Both samples also include a `test_agent_has_memory_wired()` test that verifies the callback and `PreloadMemoryTool` are correctly configured on the agent.

### 3.6. Local development with Memory Bank

When running locally with `make playground` or `agents-cli dev`, ADK uses `InMemoryMemoryService` by default. To test against a real Memory Bank instance:

```bash
uv run adk web . --port 8501 --memory_service_uri=agentengine://<AGENT_ENGINE_RESOURCE_NAME>
```

---

## 4. Artifact Storage

### 4.1. GCS artifacts in production, in-memory for local dev

Both samples support GCS-backed artifact storage via the `LOGS_BUCKET_NAME` environment variable. When unset, they fall back to in-memory storage:

**Agent Engine:**
```python
artifact_service_builder=lambda: (
    GcsArtifactService(bucket_name=logs_bucket_name)
    if logs_bucket_name
    else InMemoryArtifactService()
)
```

**Cloud Run:**
```python
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None
```

---

## 5. Telemetry and Observability

### 5.1. Built-in telemetry setup

Both samples call `setup_telemetry()` from `app.app_utils.telemetry` at startup. This configures OpenTelemetry to export traces to Cloud Trace and metrics to Cloud Monitoring.

### 5.2. Cloud Logging integration

Both samples use `google-cloud-logging` for structured logging:

```python
from google.cloud import logging as google_cloud_logging
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
```

Feedback and other structured data are logged via `logger.log_struct()`.

### 5.3. `print(flush=True)` is more reliable than `logging` on Cloud Run

Standard Python `logging.getLogger().info()` output may not appear in Cloud Run structured logs. `print(..., flush=True)` reliably appears in `gcloud run services logs read` output.

---

## 6. Testing

### 6.1. Test structure

Both samples follow the same test layout:

```
tests/
├── eval/           # ADK evaluation tests
│   ├── eval_config.json
│   └── evalsets/
├── integration/    # Integration tests (agent + deployment)
└── unit/           # Unit tests
```

### 6.2. Running tests

```bash
# Unit tests
make test

# Or directly with pytest
uv run pytest tests/unit/

# Integration tests (may require GCP credentials)
uv run pytest tests/integration/
```

### 6.3. ADK evaluations

Evaluation config and datasets live in `tests/eval/`. Run evaluations with:

```bash
make eval
```

---

## 7. Deployment

### 7.1. Agent Engine deployment

```bash
gcloud config set project <your-project-id>
make deploy
```

The `make deploy` target runs `app/app_utils/deploy.py`, which creates or updates the Agent Engine instance with `memory_bank_config` via `context_spec` in `AgentEngineConfig`.

### 7.2. Cloud Run deployment

```bash
gcloud config set project <your-project-id>
make deploy
```

The `make deploy` target builds the Docker image and deploys to Cloud Run. On first startup, the Cloud Run service creates or finds an Agent Engine instance (with Memory Bank enabled) and configures both `session_service_uri` and `memory_service_uri`. The Dockerfile runs:

```dockerfile
CMD ["uv", "run", "uvicorn", "app.fast_api_app:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 7.3. Local development

Both samples support local development with hot-reload:

```bash
make playground
```

This launches the ADK Web UI for interactive testing. You can also use `uv run adk` for direct ADK CLI access.

---

## 8. Project Scaffolding

### 8.1. These samples were generated with `agents-cli`

Both projects were scaffolded using:

```bash
# Agent Engine target
agents-cli create ae-memory-bank-sample --agent adk --deployment-target agent_engine

# Cloud Run target
agents-cli create cr-memory-bank-sample --agent adk --deployment-target cloud_run
```

The `[tool.agents-cli]` section in each `pyproject.toml` records the generation parameters, enabling CLI commands to understand project context. Each sample's README documents every change from the base template in a "Changes from Base Template" section.

---

## 9. Key Differences Between Targets

| Aspect | Agent Engine | Cloud Run |
|---|---|---|
| **Infrastructure** | Fully managed | Container-based, you own the Dockerfile |
| **Session storage** | Automatic | Must configure (`agentengine://` or in-memory) |
| **Memory Bank config** | `context_spec` in `AgentEngineConfig` (via `deploy.py`) | `context_spec` in `AgentEngineConfig` (at server startup) |
| **Memory service** | `VertexAiMemoryBankService` (automatic) | `VertexAiMemoryBankService` (via `memory_service_uri`) |
| **Entry point** | `AgentEngineApp` (AdkApp subclass) | `FastAPI` via `get_fast_api_app()` |
| **Custom endpoints** | Via `register_operations()` | Standard FastAPI routes |
| **Scaling** | Managed by Agent Engine | Cloud Run autoscaling |
| **Local dev** | `make playground` | `make playground` or `uvicorn` directly |
| **Container** | Not needed | Dockerfile required |

### When to use Agent Engine

- You want fully managed infrastructure with minimal configuration
- Session and memory management should be handled automatically
- You plan to register with Gemini Enterprise

### When to use Cloud Run

- You need full control over the serving infrastructure
- You want to add custom HTTP endpoints beyond the agent API
- You need to customize the container environment
- You want to use FastAPI middleware for auth, logging, etc.

---

## 10. Correct Imports

### Agent Engine deployments

```python
# Core ADK
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini

# Agent Engine entry point
from vertexai.agent_engines.templates.adk import AdkApp
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService

# Memory Bank (agent-level)
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

# Memory Bank (platform-level config)
from vertexai._genai.types import (
    AgentEngineConfig,
    ManagedTopicEnum,
    MemoryBankCustomizationConfig as CustomizationConfig,
    MemoryBankCustomizationConfigMemoryTopic as MemoryTopic,
    MemoryBankCustomizationConfigMemoryTopicManagedMemoryTopic as ManagedMemoryTopic,
    ReasoningEngineContextSpec,
    ReasoningEngineContextSpecMemoryBankConfig as MemoryBankConfig,
)
```

### Cloud Run deployments

```python
# Core ADK
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.cli.fast_api import get_fast_api_app

# Memory Bank (agent-level)
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

# Memory Bank (platform-level config) + Agent Engine client
import vertexai
from vertexai._genai.types import (
    AgentEngineConfig,
    ManagedTopicEnum,
    MemoryBankCustomizationConfig as CustomizationConfig,
    MemoryBankCustomizationConfigMemoryTopic as MemoryTopic,
    MemoryBankCustomizationConfigMemoryTopicManagedMemoryTopic as ManagedMemoryTopic,
    ReasoningEngineContextSpec,
    ReasoningEngineContextSpecMemoryBankConfig as MemoryBankConfig,
)
```

### Testing

```python
from google.adk.memory import InMemoryMemoryService
from google.adk.sessions import InMemorySessionService
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
```

---

## 11. Debugging Playbook

### Test locally before deploying

```bash
# Agent Engine sample
make playground

# Cloud Run sample (direct uvicorn)
uv run uvicorn app.fast_api_app:app --host localhost --port 8000
```

### Check session and memory connectivity (Cloud Run)

If the agent starts but conversations don't persist or memories aren't recalled, verify the Agent Engine resource exists and has Memory Bank configured:

```python
import vertexai
client = vertexai.Client(project="your-project", location="us-central1")
agents = list(client.agent_engines.list())
for a in agents:
    print(a.api_resource.display_name, a.api_resource.name)
```

### Use in-memory services for fast iteration

Set `USE_IN_MEMORY_SESSION=true` when you don't need persistent sessions or memories — this removes the GCP dependency for local testing.

### Verify GCP authentication

Both samples call `google.auth.default()` at import time. If this fails, ensure you've run:

```bash
gcloud auth application-default login
```

### Memory Bank not recalling memories

If Memory Bank is configured but memories aren't being recalled:
1. Verify `PreloadMemoryTool()` is in the agent's `tools` list
2. Verify `after_agent_callback` is set to `generate_memories_callback`
3. Check that the Agent Engine instance was created with `context_spec` containing `memory_bank_config`
4. Memory generation is asynchronous — new memories may not appear until the next session
