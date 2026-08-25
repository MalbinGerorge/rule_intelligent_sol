"""
Centralized LLM client construction for the Rule Analyzer (UI3).

Two deployments, deliberately used for different stakes, on TWO
SEPARATE Azure OpenAI resources (different endpoint/key/api_version
each -- not just two deployments under one shared resource):
  - GPT-5.2 (reasoning_llm): analysis, root-cause reasoning, the ReAct
    investigation loop, final report synthesis. Anywhere being wrong
    is costly. Same model already used by the Q&A agent
    (app/agent/agent_nodes.py) for the same reason.
  - GPT-4o/4.1 (fast_llm): cheap, lower-stakes sub-tasks. Not called by
    anything yet -- built now so the provider class doesn't need
    retrofitting once a genuinely lightweight step exists.

Kept as ONE class with two methods, not two separate free functions,
so callers depend on a single injectable object -- easier to swap
out/mock in tests than importing two module-level functions directly.
"""
from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from app.core.config import settings


class LLMProvider:
    def get_reasoning_llm(self, temperature: float = 0) -> AzureChatOpenAI:
        """GPT-5.2 -- analysis, reasoning, decisions."""
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_deployment=settings.azure_openai_deployment,
            temperature=temperature,
        )

    def get_fast_llm(self, temperature: float = 0) -> AzureChatOpenAI:
        """GPT-4o/4.1 -- cheap, lower-stakes sub-tasks. Reserved, not yet
        used. Separate Azure resource from get_reasoning_llm() -- own
        endpoint, key, and api_version, not just a different deployment
        name on the same resource."""
        return AzureChatOpenAI(
            azure_endpoint=settings.azure_openai_endpoint_4o,
            api_key=settings.azure_openai_api_key_4o,
            api_version=settings.azure_openai_api_version_4o,
            azure_deployment=settings.azure_openai_deployment_4o,
            temperature=temperature,
        )