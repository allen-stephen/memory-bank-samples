# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import google.auth
import vertexai
from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from vertexai._genai.types import (  # Memory Bank
    AgentEngineConfig,
    ManagedTopicEnum,
    MemoryBankCustomizationConfig as CustomizationConfig,
    MemoryBankCustomizationConfigMemoryTopic as MemoryTopic,
    MemoryBankCustomizationConfigMemoryTopicManagedMemoryTopic as ManagedMemoryTopic,
    ReasoningEngineContextSpec,
    ReasoningEngineContextSpecMemoryBankConfig as MemoryBankConfig,
)

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback

setup_telemetry()
_, project_id = google.auth.default()
logging_client = google_cloud_logging.Client()
logger = logging_client.logger(__name__)
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Memory Bank integration (not in base template) ---
# Define which memory topics the Memory Bank should extract and persist.
# This config is passed via context_spec when creating the Agent Engine
# instance, which tells the platform which information to consider meaningful.
#
# Available managed topics:
#   USER_PERSONAL_INFO     - names, relationships, hobbies, important dates
#   USER_PREFERENCES       - likes, dislikes, preferred styles
#   KEY_CONVERSATION_DETAILS - milestones, task outcomes
#   EXPLICIT_INSTRUCTIONS  - things the user asks the agent to remember/forget
#
# You can also define custom topics with CustomMemoryTopic(label=..., description=...).
# See: https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/set-up#customization-config
memory_bank_config = MemoryBankConfig(
    customization_configs=[
        CustomizationConfig(
            memory_topics=[
                MemoryTopic(
                    managed_memory_topic=ManagedMemoryTopic(
                        managed_topic_enum=ManagedTopicEnum.USER_PERSONAL_INFO,
                    ),
                ),
                MemoryTopic(
                    managed_memory_topic=ManagedMemoryTopic(
                        managed_topic_enum=ManagedTopicEnum.USER_PREFERENCES,
                    ),
                ),
                MemoryTopic(
                    managed_memory_topic=ManagedMemoryTopic(
                        managed_topic_enum=ManagedTopicEnum.EXPLICIT_INSTRUCTIONS,
                    ),
                ),
            ],
        ),
    ],
)

# Agent Engine session and memory configuration
# Check if we should use in-memory session for testing (set USE_IN_MEMORY_SESSION=true for E2E tests)
use_in_memory_session = os.environ.get("USE_IN_MEMORY_SESSION", "").lower() in (
    "true",
    "1",
    "yes",
)

if use_in_memory_session:
    # Use in-memory session/memory for local testing
    session_service_uri = None
    memory_service_uri = None
else:
    # Use environment variable for agent name, default to project name
    default_agent_name = "cr-memory-bank-sample"
    agent_name = os.environ.get("AGENT_ENGINE_SESSION_NAME", default_agent_name)

    # --- Memory Bank integration (not in base template) ---
    # Use vertexai.Client API (instead of the module-level agent_engines API)
    # so we can pass AgentEngineConfig with context_spec containing the
    # memory_bank_config when creating a new Agent Engine instance.
    agent_engine_location = os.environ.get("AGENT_ENGINE_LOCATION", "us-central1")
    client = vertexai.Client(project=project_id, location=agent_engine_location)

    existing_agents = list(client.agent_engines.list())
    matching_agents = [
        a for a in existing_agents
        if a.api_resource.display_name == agent_name
    ]

    if matching_agents:
        # Use the existing agent
        agent_engine = matching_agents[0]
    else:
        # --- Memory Bank integration (not in base template) ---
        # Create Agent Engine with memory_bank_config via context_spec so the
        # instance has Memory Bank enabled from the start.
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
    # --- Memory Bank integration (not in base template) ---
    # The memory service uses the same Agent Engine instance as the session
    # service. Setting memory_service_uri tells ADK to use
    # VertexAiMemoryBankService, which works with the PreloadMemoryTool and
    # generate_memories_callback defined in agent.py.
    memory_service_uri = session_service_uri

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    # --- Memory Bank integration (not in base template) ---
    memory_service_uri=memory_service_uri,
    otel_to_cloud=True,
)
app.title = "cr-memory-bank-sample"
app.description = "API for interacting with the Agent cr-memory-bank-sample"


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
