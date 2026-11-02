"""Composition root: the only place that knows which concrete adapters exist."""

from __future__ import annotations

from agent.budget import Limits
from agent.config import Settings
from agent.gate import ApprovalGate, Approver
from agent.loop import Agent
from agent.models.base import ModelClient
from agent.models.pricing import price_for
from agent.prompts import SYSTEM_PROMPT
from agent.retrieval.chunker import load_corpus
from agent.retrieval.embedders import Embedder
from agent.retrieval.index import Mode, Retriever
from agent.tools.github import AllowlistedGitHub, GitHubClient, github_tools
from agent.tools.notes import notes_tool
from agent.tools.registry import ToolRegistry


def build_model(s: Settings) -> ModelClient:
    if s.model_provider == "gemini":
        from agent.models.gemini import GeminiClient

        return GeminiClient(
            s.gemini_api_key, s.model_name, seed=s.seed, timeout_s=s.step_timeout_s, rpm=s.model_rpm
        )
    if s.model_provider == "openai_compat":
        from agent.models.openai_compat import OpenAICompatClient

        return OpenAICompatClient(
            s.model_base_url, s.model_api_key, s.model_name, seed=s.seed, timeout_s=s.step_timeout_s, rpm=s.model_rpm
        )
    raise ValueError(f"unknown MODEL_PROVIDER {s.model_provider!r} (supported: gemini, openai_compat)")


def build_embedder(s: Settings) -> Embedder:
    from agent.retrieval.embedders import FastEmbedEmbedder

    return FastEmbedEmbedder(s.embed_model, cache_dir=str(s.cache_dir / "fastembed"))


def build_github(s: Settings, *, offline: bool) -> GitHubClient:
    if offline:
        from agent.tools.fake_github import FakeGitHub

        return FakeGitHub.from_sandbox(s.github_repo or "owner/ledgerly-api")
    from agent.tools.http_github import HttpGitHub

    return HttpGitHub(s.github_token, s.github_repo)


def build_retriever(s: Settings, embedder: Embedder, mode: str | None = None) -> Retriever:
    return Retriever(
        load_corpus(s.corpus_dir),
        embedder,
        mode=Mode(mode or s.retrieval_mode),
        cache_dir=s.cache_dir / "index",
    )


def build_agent(
    s: Settings,
    *,
    approver: Approver,
    model: ModelClient | None = None,
    github: GitHubClient | None = None,
    retriever: Retriever | None = None,
    offline_github: bool = False,
) -> Agent:
    model = model or build_model(s)
    gh = github or build_github(s, offline=offline_github)
    retriever = retriever or build_retriever(s, build_embedder(s))
    allow = set(s.write_allowlist) | ({gh.repo} if offline_github else set())
    tools = ToolRegistry(
        [notes_tool(retriever), *github_tools(AllowlistedGitHub(gh, allow))],
        gate=ApprovalGate(approver),
    )
    return Agent(
        model,
        tools,
        price=price_for(model.model_name),
        trace_dir=s.trace_dir,
        system_prompt=SYSTEM_PROMPT,
        limits=Limits(max_steps=s.max_steps, max_cost_usd=s.max_cost_usd, step_timeout_s=s.step_timeout_s),
    )
