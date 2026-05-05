"""Keyword generation agent for psychology literature search.

This agent uses LangGraph to generate comprehensive search keywords for psychology
research queries, including synonyms, related terms, and domain-specific vocabulary.
"""

import logging
import os
import re
from typing import List, Dict, Any, Optional, TypedDict
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from pydantic import BaseModel, ValidationError, Field

    _HAS_PYDANTIC = True
except Exception:
    _HAS_PYDANTIC = False

if _HAS_PYDANTIC:

    class KeywordSchema(BaseModel):
        primary_keywords: list[str] = Field(default_factory=list)
        synonyms: list[str] = Field(default_factory=list)
        related_terms: list[str] = Field(default_factory=list)
        domain_terms: list[str] = Field(default_factory=list)
        outcome_terms: list[str] = Field(default_factory=list)
        design_terms: list[str] = Field(default_factory=list)
        population_terms: list[str] = Field(default_factory=list)
        measurement_terms: list[str] = Field(default_factory=list)
        context_terms: list[str] = Field(default_factory=list)


from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import StateGraph, END
import yaml
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from metaagent.config import load_runtime_env

load_runtime_env(module_hint="screening")


@dataclass
class KeywordSet:
    """Represents a set of generated keywords."""

    primary_keywords: List[str]
    synonyms: List[str]
    related_terms: List[str]
    domain_terms: List[str]  # Psychology-specific terms
    outcome_terms: List[str] = field(default_factory=list)
    design_terms: List[str] = field(default_factory=list)
    population_terms: List[str] = field(default_factory=list)
    measurement_terms: List[str] = field(default_factory=list)
    context_terms: List[str] = field(default_factory=list)
    search_queries: List[str] = field(
        default_factory=list
    )  # Formatted queries ready for search

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "primary_keywords": self.primary_keywords,
            "synonyms": self.synonyms,
            "related_terms": self.related_terms,
            "domain_terms": self.domain_terms,
            "outcome_terms": self.outcome_terms,
            "design_terms": self.design_terms,
            "population_terms": self.population_terms,
            "measurement_terms": self.measurement_terms,
            "context_terms": self.context_terms,
            "search_queries": self.search_queries,
        }

    def get_all_keywords(self) -> List[str]:
        """Get all keywords as a flat list."""
        return (
            self.primary_keywords
            + self.synonyms
            + self.related_terms
            + self.domain_terms
            + self.outcome_terms
            + self.design_terms
            + self.population_terms
            + self.measurement_terms
            + self.context_terms
        )


class KeywordGeneratorState(TypedDict):
    """State for keyword generation agent."""

    research_query: str
    domain: str  # e.g., "psychology", "clinical_psychology", "cognitive_psychology"
    context: Optional[str]
    keywords: Optional[KeywordSet]
    iteration: int
    max_iterations: int
    error: Optional[str]


class KeywordGeneratorAgent:
    """Agent for generating search keywords from research queries."""

    def __init__(
        self,
        llm_provider: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_iterations: int = 3,
        config_path: Optional[Path] = None,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        """Initialize keyword generator agent.

        Args:
            llm_provider: LLM provider ("claude", "openai", or custom).
                         If None, reads from LLM_PROVIDER env var or config.
            model_name: Model name. If None, reads from LLM_MODEL env var or config.
            temperature: LLM temperature. If None, reads from config or uses 0.7.
            max_iterations: Maximum agent iterations
            config_path: Path to config file
            api_key: API key. If None, reads from environment variables:
                     - ANTHROPIC_API_KEY (for claude)
                     - OPENAI_API_KEY (for openai)
                     - LLM_API_KEY (generic fallback)
            api_base: Custom API base URL (for custom providers)
        """
        self.max_iterations = max_iterations

        # Load config
        if config_path is None:
            config_path = (
                Path(__file__).parent.parent.parent.parent
                / "configs"
                / "agent_config.yaml"
            )

        self.config = self._load_config(config_path)

        # Initialize LLM - prioritize env vars, then args, then config
        llm_config = self.config.get("llm", {})

        # Get provider from env var, arg, or config
        provider = (
            llm_provider
            if llm_provider is not None
            else os.getenv("LLM_PROVIDER") or llm_config.get("provider", "claude")
        ).lower()

        # Get model from env var, arg, or config
        model = (
            model_name
            if model_name is not None
            else os.getenv("LLM_MODEL")
            or llm_config.get("model", "claude-3-5-sonnet-20241022")
        )

        # Get temperature from arg, env var, or config
        temp = (
            temperature
            if temperature is not None
            else float(os.getenv("LLM_TEMPERATURE", llm_config.get("temperature", 0.7)))
        )

        # Log configuration for debugging
        logger.info(
            f"LLM Configuration: provider={provider}, model={model}, temperature={temp}"
        )
        logger.info(
            f"Environment variables - LLM_PROVIDER={os.getenv('LLM_PROVIDER')}, "
            f"LLM_MODEL={os.getenv('LLM_MODEL')}, "
            f"LLM_BASE_URL={os.getenv('LLM_BASE_URL')}, "
            f"LLM_API_BASE={os.getenv('LLM_API_BASE')}, "
            f"OPENAI_BASE_URL={os.getenv('OPENAI_BASE_URL')}, "
            f"OPENAI_API_BASE={os.getenv('OPENAI_API_BASE')}"
        )

        # Get API key
        api_key = api_key or self._get_api_key(provider)
        logger.info(f"API key found: {'Yes' if api_key else 'No'}")
        self.api_key = api_key
        self.raw_openai_client = None

        # Get API base URL (check multiple env vars for compatibility)
        # Support both LLM_BASE_URL and LLM_API_BASE for flexibility
        api_base = (
            api_base
            or os.getenv("LLM_BASE_URL")
            or os.getenv("LLM_API_BASE")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("OPENAI_API_BASE")
            or os.getenv("SILICONFLOW_BASE_URL")
            or os.getenv("SILICONFLOW_API_BASE")
        )
        logger.info(f"API base URL: {api_base or 'Not set'}")
        # Persist key runtime values for adapters/fallbacks
        self.api_base = api_base
        self.provider = provider
        self.model = model

        # Initialize LLM based on provider
        self.llm = self._create_llm(
            provider=provider,
            model=model,
            temperature=temp,
            api_key=api_key,
            api_base=api_base,
        )

        # Build agent graph
        self.agent = self._build_agent()

    def _get_api_key(self, provider: str) -> Optional[str]:
        """Get API key from environment variables."""
        provider_lower = provider.lower()

        if provider_lower == "claude":
            return os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY")
        elif provider_lower == "openai":
            return os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
        elif provider_lower in ["siliconflow", "qwen"]:
            # SiliconFlow specific env vars
            return (
                os.getenv("QWEN_API_KEY")
                or os.getenv("SILICONFLOW_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("LLM_API_KEY")
            )
        else:
            # For custom providers, try multiple env vars
            return (
                os.getenv("LLM_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or os.getenv(f"{provider.upper()}_API_KEY")
            )

    def _create_llm(
        self,
        provider: str,
        model: str,
        temperature: float,
        api_key: Optional[str],
        api_base: Optional[str],
    ) -> BaseChatModel:
        """Create LLM instance based on provider.

        Supports:
        - Claude (Anthropic)
        - OpenAI
        - SiliconFlow and other OpenAI-compatible APIs (via LLM_API_BASE)
        """
        # Check if using OpenAI-compatible API (SiliconFlow, etc.)
        # If api_base is set, use OpenAI-compatible interface regardless of provider name
        if api_base or provider not in ["claude", "openai"]:
            # Use OpenAI-compatible API for custom providers or when api_base is set
            if not api_key:
                # Try to get from common env vars
                api_key = (
                    os.getenv("OPENAI_API_KEY")
                    or os.getenv("LLM_API_KEY")
                    or os.getenv("SILICONFLOW_API_KEY")
                )
                if not api_key:
                    raise ValueError(
                        "API key is required. Please set one of: "
                        "OPENAI_API_KEY, LLM_API_KEY, or SILICONFLOW_API_KEY"
                    )

            # Get API base URL
            if not api_base:
                api_base = (
                    os.getenv("LLM_BASE_URL")
                    or os.getenv("LLM_API_BASE")
                    or os.getenv("OPENAI_BASE_URL")
                    or os.getenv("OPENAI_API_BASE")
                    or os.getenv("SILICONFLOW_BASE_URL")
                    or os.getenv("SILICONFLOW_API_BASE")
                )

            # Default SiliconFlow API base if not specified
            if not api_base and provider.lower() in ["siliconflow", "qwen"]:
                api_base = "https://api.siliconflow.cn/v1"
                logger.info(f"Using SiliconFlow API base: {api_base}")

            if not api_base:
                raise ValueError(
                    "API base URL is required for custom providers. "
                    "Please set LLM_BASE_URL, LLM_API_BASE, OPENAI_BASE_URL, or OPENAI_API_BASE environment variable. "
                    "For SiliconFlow, use: https://api.siliconflow.cn/v1"
                )

            # Use OpenAI-compatible interface
            logger.info(f"Using OpenAI-compatible API: {api_base}")

            # Workaround for 'proxies' parameter error in some langchain-openai versions
            # Create OpenAI client directly and pass it to ChatOpenAI
            try:
                import openai
                from openai import OpenAI

                # Create OpenAI client with custom base URL
                client = OpenAI(
                    api_key=api_key,
                    base_url=api_base,
                )
                # store raw OpenAI v1 client for direct calls
                try:
                    self.raw_openai_client = client
                except Exception:
                    self.raw_openai_client = None

                # Use ChatOpenAI with the custom client
                try:
                    return ChatOpenAI(
                        model=model,
                        temperature=temperature,
                        client=client,
                    )
                except TypeError as te:
                    # If ChatOpenAI raises TypeError, surface clear guidance
                    if "proxies" in str(te) or "unexpected keyword argument" in str(te):
                        raise RuntimeError(
                            "Incompatible 'openai' / 'langchain_openai' versions detected: ``Client.__init__() got an unexpected keyword argument 'proxies'``.\n"
                            "This usually means the installed 'openai' package and 'langchain_openai' (or langchain) are incompatible.\n"
                            "Possible fixes:\n"
                            "  1) Upgrade packages: `pip install --upgrade openai langchain-openai langchain`\n"
                            "  2) If the problem persists, try pinning versions known to work together (consult your project's README).\n"
                            "  3) As a temporary workaround, set environment variables `OPENAI_API_BASE` and `OPENAI_API_KEY` and instantiate a provider-specific client.\n"
                            "After updating packages, re-run your script."
                        ) from te
                    raise
            except Exception as e:
                # If the low-level OpenAI client construction fails with 'proxies', provide clearer instructions
                if "proxies" in str(e) or "unexpected keyword argument" in str(e):
                    raise RuntimeError(
                        "Failed to initialize OpenAI client due to incompatible 'openai' package.\n"
                        "Error: Client.__init__() got an unexpected keyword argument 'proxies'.\n"
                        "Please try updating/downgrading the 'openai' and 'langchain_openai' packages so they match.\n"
                        "Example: `pip install --upgrade openai langchain-openai langchain`\n"
                    ) from e
                logger.warning(
                    f"Failed to create OpenAI client directly: {e}, trying alternative method"
                )
                # Fallback: use environment variables
                original_base = os.getenv("OPENAI_API_BASE")
                original_key = os.getenv("OPENAI_API_KEY")
                try:
                    os.environ["OPENAI_API_BASE"] = api_base
                    os.environ["OPENAI_API_KEY"] = api_key
                    try:
                        return ChatOpenAI(
                            model=model,
                            temperature=temperature,
                        )
                    except TypeError as te2:
                        if "proxies" in str(
                            te2
                        ) or "unexpected keyword argument" in str(te2):
                            raise RuntimeError(
                                "Detected incompatible 'openai' / 'langchain_openai' interaction when creating ChatOpenAI.\n"
                                "Please align package versions (see: https://pypi.org/project/openai/) or set up a provider-specific client.\n"
                            ) from te2
                        raise
                finally:
                    if original_base is not None:
                        os.environ["OPENAI_API_BASE"] = original_base
                    elif "OPENAI_API_BASE" in os.environ:
                        del os.environ["OPENAI_API_BASE"]
                    if original_key is not None:
                        os.environ["OPENAI_API_KEY"] = original_key
                    elif "OPENAI_API_KEY" in os.environ:
                        del os.environ["OPENAI_API_KEY"]

        elif provider == "claude":
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY or LLM_API_KEY environment variable is required for Claude"
                )
            return ChatAnthropic(
                model=model,
                temperature=temperature,
                anthropic_api_key=api_key,
            )
        elif provider == "openai":
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY or LLM_API_KEY environment variable is required for OpenAI"
                )
            # Try new parameter names first, fallback to old ones
            try:
                kwargs = {
                    "model": model,
                    "temperature": temperature,
                    "api_key": api_key,
                }
                if api_base:
                    kwargs["base_url"] = api_base
                return ChatOpenAI(**kwargs)
            except TypeError:
                # Fallback for older versions
                kwargs = {
                    "model": model,
                    "temperature": temperature,
                    "openai_api_key": api_key,
                }
                if api_base:
                    kwargs["openai_api_base"] = api_base
                return ChatOpenAI(**kwargs)
        else:
            # Fallback: try OpenAI-compatible API
            if not api_key:
                api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
            if api_key:
                logger.warning(
                    f"Unknown provider '{provider}', trying OpenAI-compatible API"
                )
                fallback_base = (
                    api_base or os.getenv("LLM_BASE_URL") or os.getenv("LLM_API_BASE")
                )
                try:
                    return ChatOpenAI(
                        model=model,
                        temperature=temperature,
                        api_key=api_key,
                        base_url=fallback_base,
                    )
                except TypeError:
                    return ChatOpenAI(
                        model=model,
                        temperature=temperature,
                        openai_api_key=api_key,
                        openai_api_base=fallback_base,
                    )
            raise ValueError(
                f"Unsupported provider: {provider}. "
                "Supported providers: 'claude', 'openai', or any OpenAI-compatible API "
                "(set LLM_API_BASE for custom providers)"
            )

    def _load_config(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")
        return {}

    def _build_agent(self) -> StateGraph:
        """Build LangGraph agent for keyword generation."""
        workflow = StateGraph(KeywordGeneratorState)

        # Add nodes
        workflow.add_node("analyze_query", self._analyze_query)
        workflow.add_node("generate_keywords", self._generate_keywords)
        workflow.add_node("refine_keywords", self._refine_keywords)

        # Define edges
        workflow.set_entry_point("analyze_query")
        workflow.add_edge("analyze_query", "generate_keywords")
        workflow.add_conditional_edges(
            "generate_keywords",
            self._should_refine,
            {
                "refine": "refine_keywords",
                "end": END,
            },
        )
        workflow.add_edge("refine_keywords", END)

        return workflow.compile()

    def _call_llm(self, messages):
        """Adapter for calling the LLM client and returning a simple response object with `content`.

        Supports different client implementations that may provide `invoke`, `create`, or are callables.
        Returns an object with a `.content` attribute (string).
        """

        class _Resp:
            def __init__(self, content: str):
                self.content = content

        def _to_openai_messages(msgs):
            out = []
            for m in msgs:
                role = getattr(m, "role", None)
                if role is None:
                    # Map langchain-style message classes
                    if isinstance(m, SystemMessage):
                        role = "system"
                    elif isinstance(m, HumanMessage):
                        role = "user"
                    else:
                        role = "user"
                content = getattr(m, "content", str(m))
                out.append({"role": role, "content": content})
            return out

        last_error: Optional[Exception] = None

        # 1) Try common high-level interfaces
        try:
            # Prefer direct OpenAI v1 client if available
            raw_client = getattr(self, "raw_openai_client", None)
            if raw_client is not None:
                try:
                    msgs = _to_openai_messages(messages)
                    resp = raw_client.chat.completions.create(
                        model=getattr(self, "model", None), messages=msgs
                    )
                    # resp may be a dict-like or object
                    if hasattr(resp, "choices") and resp.choices:
                        choice = resp.choices[0]
                        content = (
                            getattr(getattr(choice, "message", None), "content", None)
                            or getattr(choice, "text", None)
                            or str(resp)
                        )
                        return _Resp(content)
                    # dict-like
                    if isinstance(resp, dict) and resp.get("choices"):
                        choice = resp["choices"][0]
                        msg = choice.get("message") or {}
                        content = msg.get("content") or choice.get("text") or str(resp)
                        return _Resp(content)
                except Exception:
                    # if raw client call fails, continue to other adapters
                    pass
            if hasattr(self.llm, "invoke"):
                return self.llm.invoke(messages)

            create_fn = getattr(self.llm, "create", None)
            if callable(create_fn):
                msgs = _to_openai_messages(messages)
                try:
                    resp = create_fn(messages=msgs)
                except Exception:
                    # some wrappers expect 'input' or different kwarg
                    resp = create_fn(input=msgs)

                # Try to extract content
                if hasattr(resp, "choices") and resp.choices:
                    choice = resp.choices[0]
                    # new SDK: choice.message.content
                    content = (
                        getattr(getattr(choice, "message", None), "content", None)
                        or getattr(choice, "text", None)
                        or str(resp)
                    )
                    return _Resp(content)
                if hasattr(resp, "content"):
                    return _Resp(str(resp.content))
                return _Resp(str(resp))

            # 2) Try underlying client attributes (client/root_client/openai)
            client = (
                getattr(self.llm, "client", None)
                or getattr(self.llm, "root_client", None)
                or getattr(self.llm, "openai", None)
            )
            if client is not None:
                msgs = _to_openai_messages(messages)
                # Try common nested call patterns
                for attr_path in (
                    "chat.completions.create",
                    "chat.completions.create",
                    "create",
                ):
                    parts = attr_path.split(".")
                    target = client
                    try:
                        for p in parts:
                            target = getattr(target, p)
                        if callable(target):
                            resp = target(
                                model=getattr(self, "model", None), messages=msgs
                            )
                            # extract
                            if hasattr(resp, "choices") and resp.choices:
                                choice = resp.choices[0]
                                content = (
                                    getattr(
                                        getattr(choice, "message", None),
                                        "content",
                                        None,
                                    )
                                    or getattr(choice, "text", None)
                                    or str(resp)
                                )
                                return _Resp(content)
                            return _Resp(str(resp))
                    except Exception:
                        continue

            # 3) If llm is callable, call it and adapt
            if callable(self.llm):
                out = self.llm(messages)
                if isinstance(out, str):
                    return _Resp(out)
                if hasattr(out, "content"):
                    return out
                return _Resp(str(out))

        except Exception as e:
            # If we detected a known incompatibility, log and allow HTTP fallback to attempt
            last_error = e
            msg = str(e)
            logger.debug(f"_call_llm: caught exception {msg}")
            if "has no attribute 'create'" in msg or "OpenAIWithRawResponse" in msg:
                logger.warning(
                    "Detected LLM client wrapper without 'create' (e.g. OpenAIWithRawResponse). "
                    "Will attempt direct HTTP API fallback. Error: %s",
                    msg,
                )
            else:
                logger.warning(
                    "LLM client call failed, will try HTTP fallback: %s", msg
                )

        # 4) Final fallback: try calling the provider HTTP API directly (OpenAI-compatible)
        try:
            base = (
                getattr(self, "api_base", None)
                or os.getenv("LLM_BASE_URL")
                or os.getenv("LLM_API_BASE")
                or os.getenv("OPENAI_API_BASE")
                or os.getenv("SILICONFLOW_BASE_URL")
            )
            key = (
                getattr(self, "api_key", None)
                or os.getenv("SILICONFLOW_API_KEY")
                or os.getenv("QWEN_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or os.getenv("LLM_API_KEY")
            )
            model = getattr(self, "model", None) or os.getenv("LLM_MODEL")
            if base and key and model:
                url = base.rstrip("/") + "/chat/completions"

                payload = {
                    "model": model,
                    "messages": _to_openai_messages(messages),
                }
                try:
                    payload["temperature"] = float(os.getenv("LLM_TEMPERATURE"))
                except Exception:
                    pass

                # Create session with retries/backoff
                session = requests.Session()
                retries = Retry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=(429, 500, 502, 503, 504),
                    raise_on_status=False,
                )
                adapter = HTTPAdapter(max_retries=retries)
                session.mount("https://", adapter)
                session.mount("http://", adapter)

                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }

                resp = session.post(url, json=payload, headers=headers, timeout=30)
                try:
                    resp.raise_for_status()
                except Exception as e:
                    logger.warning(
                        f"HTTP fallback request failed: {e} (status {getattr(resp, 'status_code', None)})"
                    )
                    raise

                data = resp.json()
                # Extract content
                if "choices" in data and data["choices"]:
                    choice = data["choices"][0]
                    msg = choice.get("message") or {}
                    content = msg.get("content") or choice.get("text") or str(data)
                    return type("Resp", (), {"content": content})
                return type("Resp", (), {"content": str(data)})
        except Exception as e:
            last_error = e
            logger.debug(f"HTTP fallback to provider failed: {e}")

        # If nothing worked, raise informative error
        if last_error:
            raise RuntimeError(
                "LLM call failed after all fallbacks; see logs for details"
            ) from last_error
        raise RuntimeError(
            "Unsupported LLM client interface: no usable 'invoke'/'create'/'client' found; see logs for details"
        )

    def _extract_content(self, response) -> str:
        """Extract a text content string from various LLM response shapes."""
        import json

        if response is None:
            return ""
        # Plain string
        if isinstance(response, str):
            return response

        # Common attribute used earlier
        if hasattr(response, "content") and response.content:
            return str(response.content)

        # Some wrappers use .text
        if hasattr(response, "text") and response.text:
            return str(response.text)

        # openai-like choices
        if hasattr(response, "choices") and response.choices:
            try:
                choice = response.choices[0]
                msg = getattr(choice, "message", None)
                if msg is not None and getattr(msg, "content", None):
                    return str(msg.content)
                if getattr(choice, "text", None):
                    return str(choice.text)
            except Exception:
                pass

        # Try raw members
        for attr in ("raw_response", "_raw_response", "response", "_response", "data"):
            val = getattr(response, attr, None)
            if val:
                try:
                    return json.dumps(val)
                except Exception:
                    return str(val)

        # Fallback: try to stringify __dict__
        try:
            return json.dumps(getattr(response, "__dict__", str(response)))
        except Exception:
            return str(response)

    def _analyze_query(self, state: KeywordGeneratorState) -> KeywordGeneratorState:
        """Analyze research query to determine domain and context."""
        logger.info(f"Analyzing query: {state['research_query']}")

        # Determine domain from query or use default
        domain = state.get("domain", "epidemiology")

        # Use LLM to analyze query and suggest domain
        prompt = f"""Analyze this epidemiology research query and determine the most relevant subdomain:

Query: {state['research_query']}

Possible domains: infectious_disease, chronic_disease, environmental_epi, 
occupational_epi, genetic_epi, social_epi, cancer_epi, cardiovascular_epi, 
nutritional_epi, or general epidemiology.

Respond with only the domain name (e.g., "infectious_disease")."""

        try:
            response = self._call_llm([HumanMessage(content=prompt)])
            suggested_domain = self._extract_content(response).strip().lower()
            # Validate domain
            valid_domains = [
                "infectious_disease",
                "chronic_disease",
                "environmental_epi",
                "occupational_epi",
                "genetic_epi",
                "social_epi",
                "cancer_epi",
                "cardiovascular_epi",
                "nutritional_epi",
                "epidemiology",
            ]
            if suggested_domain in valid_domains:
                domain = suggested_domain
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Failed to analyze domain: {error_msg}, using default")
            # Provide helpful error message
            if "Connection" in error_msg or "timeout" in error_msg.lower():
                logger.error(
                    "Connection error detected. Please check:\n"
                    "1. Your API key is correct\n"
                    "2. Your API base URL is correct (for SiliconFlow: https://api.siliconflow.cn/v1)\n"
                    "3. Your network connection is working\n"
                    "4. The LLM_PROVIDER environment variable is set correctly"
                )

        state["domain"] = domain
        state["iteration"] = 0
        state["error"] = None

        return state

    def _generate_keywords(self, state: KeywordGeneratorState) -> KeywordGeneratorState:
        """Generate keywords using LLM."""
        logger.info("Generating keywords...")

        research_query = state["research_query"]
        domain = state["domain"]
        iteration = state.get("iteration", 0)

        system_prompt, user_prompt_template, refine_prompt = self._get_keyword_prompts()
        user_prompt = user_prompt_template.format(
            research_query=research_query,
            domain=domain,
            context=state.get("context") or "",
        )

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = self._call_llm(messages)

            # Parse JSON response
            import json
            import re

            # Extract JSON from response
            content = self._extract_content(response).strip()
            logger.debug("Extracted LLM content (repr): %s", repr(content))
            logger.debug("LLM raw response object: %s", repr(response))
            if not content:
                logger.warning(
                    "LLM returned empty content or unparsable response: %s",
                    repr(response),
                )
                raise ValueError("Empty LLM response")
            # Try to find JSON object
            json_match = re.search(r"\{.*?\}", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                keywords_dict = json.loads(json_str)
            else:
                # Fallback: try parsing entire content
                keywords_dict = json.loads(content)

            # Validate/normalize structure
            if _HAS_PYDANTIC:
                try:
                    ks = KeywordSchema(**keywords_dict)
                    keywords_dict = ks.dict()
                except ValidationError as ve:
                    logger.warning(f"Keyword JSON failed validation: {ve}")
                    # fall back to best-effort extraction
            else:
                # Basic normalization: ensure keys exist and are lists
                for k in [
                    "primary_keywords",
                    "synonyms",
                    "related_terms",
                    "domain_terms",
                    "outcome_terms",
                    "design_terms",
                    "population_terms",
                    "measurement_terms",
                    "context_terms",
                ]:
                    v = keywords_dict.get(k)
                    if not isinstance(v, list):
                        keywords_dict[k] = [v] if v else []

            # Create KeywordSet
            keyword_set = KeywordSet(
                primary_keywords=keywords_dict.get("primary_keywords", []),
                synonyms=keywords_dict.get("synonyms", []),
                related_terms=keywords_dict.get("related_terms", []),
                domain_terms=keywords_dict.get("domain_terms", []),
                outcome_terms=keywords_dict.get("outcome_terms", []),
                design_terms=keywords_dict.get("design_terms", []),
                population_terms=keywords_dict.get("population_terms", []),
                measurement_terms=keywords_dict.get("measurement_terms", []),
                context_terms=keywords_dict.get("context_terms", []),
                search_queries=[],  # Will be generated in refine step
            )

            # Generate search queries
            keyword_set.search_queries = self._generate_search_queries(keyword_set)

            state["keywords"] = keyword_set
            state["iteration"] = iteration + 1
            state["error"] = None

            logger.info(f"Generated {len(keyword_set.get_all_keywords())} keywords")

        except Exception as e:
            logger.error(f"Error generating keywords: {e}")
            state["error"] = str(e)
            # Create empty keyword set as fallback
            state["keywords"] = KeywordSet(
                primary_keywords=[research_query],
                synonyms=[],
                related_terms=[],
                domain_terms=[],
                search_queries=[research_query],
            )

        return state

    def _generate_search_queries(self, keyword_set: KeywordSet) -> List[str]:
        """Generate formatted search queries from keywords."""
        queries = []

        def _or_group(terms: List[str]) -> str:
            cleaned = [self._format_term(t) for t in terms if t]
            if not cleaned:
                return ""
            if len(cleaned) == 1:
                return cleaned[0]
            return "(" + " OR ".join(cleaned) + ")"

        construct_terms = keyword_set.primary_keywords[:4] + keyword_set.synonyms[:4]
        outcome_terms = keyword_set.outcome_terms[:4]
        design_terms = keyword_set.design_terms[:4]
        population_terms = keyword_set.population_terms[:4]
        measurement_terms = keyword_set.measurement_terms[:3]

        if construct_terms and outcome_terms and design_terms:
            queries.append(
                f"{_or_group(construct_terms)} AND {_or_group(outcome_terms)} AND {_or_group(design_terms)}"
            )
        if construct_terms and outcome_terms:
            queries.append(
                f"{_or_group(construct_terms)} AND {_or_group(outcome_terms)}"
            )
        if construct_terms and design_terms:
            queries.append(
                f"{_or_group(construct_terms)} AND {_or_group(design_terms)}"
            )
        if construct_terms and population_terms:
            queries.append(
                f"{_or_group(construct_terms)} AND {_or_group(population_terms)}"
            )
        if construct_terms and measurement_terms:
            queries.append(
                f"{_or_group(construct_terms)} AND {_or_group(measurement_terms)}"
            )

        # Single keyword queries
        for keyword in keyword_set.primary_keywords[:5]:
            queries.append(self._format_term(keyword))

        # Combined queries (2-3 keywords)
        primary = keyword_set.primary_keywords[:3]
        synonyms = keyword_set.synonyms[:2]

        if len(primary) >= 2:
            queries.append(
                f"{self._format_term(primary[0])} AND {self._format_term(primary[1])}"
            )

        if len(primary) >= 1 and len(synonyms) >= 1:
            queries.append(
                f"{self._format_term(primary[0])} AND {self._format_term(synonyms[0])}"
            )

        # Domain-specific combinations
        if keyword_set.domain_terms:
            for domain_term in keyword_set.domain_terms[:2]:
                if primary:
                    queries.append(
                        f"{self._format_term(primary[0])} AND {self._format_term(domain_term)}"
                    )

        return queries[:10]  # Limit to 10 queries

    def _format_term(self, term: str) -> str:
        """Quote multi-word terms to improve search compatibility."""
        if term is None:
            return ""
        cleaned = str(term).strip()
        if not cleaned:
            return ""
        if any(ch.isspace() for ch in cleaned) or any(ch in '()"' for ch in cleaned):
            escaped = cleaned.replace('"', '\\"')
            return f'"{escaped}"'
        return cleaned

    def _should_refine(self, state: KeywordGeneratorState) -> str:
        """Determine if keywords should be refined."""
        iteration = state.get("iteration", 0)
        max_iter = state.get("max_iterations", self.max_iterations)
        keywords = state.get("keywords")

        # Check if we should refine
        if iteration >= max_iter:
            return "end"

        if keywords is None:
            return "end"

        # Check if keywords are sufficient
        all_keywords = keywords.get_all_keywords()
        if len(all_keywords) < 5:
            return "refine"

        # If no error and sufficient keywords, end
        if state.get("error") is None:
            return "end"

        return "refine"

    def _refine_keywords(self, state: KeywordGeneratorState) -> KeywordGeneratorState:
        """Refine existing keywords."""
        logger.info("Refining keywords...")

        research_query = state["research_query"]
        existing_keywords = state.get("keywords")

        if existing_keywords is None:
            return self._generate_keywords(state)

        # Use LLM to expand keywords
        _, _, refine_prompt = self._get_keyword_prompts()
        prompt = refine_prompt.format(
            research_query=research_query,
            existing_keywords=existing_keywords.get_all_keywords()[:20],
        )

        try:
            response = self._call_llm([HumanMessage(content=prompt)])

            import json
            import re

            content = self._extract_content(response).strip()
            logger.debug("Extracted LLM content (repr): %s", repr(content))
            logger.debug("LLM raw response object: %s", repr(response))
            if not content:
                logger.warning(
                    "LLM returned empty content or unparsable response: %s",
                    repr(response),
                )
                raise ValueError("Empty LLM response")
            json_match = re.search(r"\[.*?\]", content, re.DOTALL)
            if json_match:
                additional_keywords = json.loads(json_match.group(0))
            else:
                additional_keywords = json.loads(content)

            # Validate additional keywords list
            if not isinstance(additional_keywords, list):
                additional_keywords = [str(additional_keywords)]

            # Add to related_terms
            existing_keywords.related_terms.extend(additional_keywords[:10])

            # Regenerate search queries
            existing_keywords.search_queries = self._generate_search_queries(
                existing_keywords
            )

            state["keywords"] = existing_keywords
            state["iteration"] = state.get("iteration", 0) + 1
            state["error"] = None

        except Exception as e:
            logger.error(f"Error refining keywords: {e}")
            state["error"] = str(e)

        return state

    def _get_keyword_prompts(self) -> tuple[str, str, str]:
        """Load keyword prompts from file, fallback to defaults."""
        if hasattr(self, "_keyword_prompts"):
            return self._keyword_prompts  # type: ignore[attr-defined]

        default_system = (
            "You are an expert in epidemiology literature search with deep knowledge of PubMed indexing.\n"
            "Your task is to generate RETRIEVAL-OPTIMIZED keywords for academic databases.\n\n"
            "🚨 CRITICAL: Distinguish between CONCEPT SPACE and RETRIEVAL SPACE\n"
            "- Concept: What researchers THINK about (e.g., 'isolation delay interval')\n"
            "- Retrieval: What authors WRITE in papers (e.g., 'isolation', 'delay', 'interval')\n"
            "YOU MUST GENERATE RETRIEVAL TERMS, NOT CONCEPT LABELS.\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "📊 QUANTITY LIMITS (STRICTLY ENFORCE):\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "- primary_keywords: 3-5 SINGLE WORDS or STANDARD TERMS (NO compound phrases)\n"
            "- synonyms: 5-8 TRUE SYNONYMS (exact same meaning, not variations)\n"
            "- related_terms: 5-10 closely related concepts\n"
            "- domain_terms: 3-5 epidemiological methods\n"
            "- outcome_terms: 3-5 key health outcomes\n"
            "- design_terms: 3-5 study designs\n"
            "- population_terms: 3-5 if applicable (use empty list if not relevant)\n"
            "- measurement_terms: 3-5 if applicable (use empty list if not relevant)\n"
            "- context_terms: 3-5 if applicable (use empty list if not relevant)\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "🚫 PHRASE COMPOSITION RULES (CRITICAL FOR IDI/DELAY RESEARCH):\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "For STANDARDIZED INTERVALS (serial interval, incubation period):\n"
            "  ✓ Use standard medical term: 'serial interval', 'incubation period'\n\n"
            "For OPERATIONAL DELAYS (isolation delay, testing delay, reporting delay):\n"
            "  ✗ NEVER invent compound phrases: 'isolation delay', 'case isolation delay'\n"
            "  ✓ DECOMPOSE into atomic terms: 'isolation', 'delay', 'interval'\n"
            "  ✓ Let query builder use AND logic: (isolation AND delay)\n\n"
            "BANNED PATTERNS (will cause PubMed errors):\n"
            "  ✗ 'X delay' (e.g., 'isolation delay', 'testing delay')\n"
            "  ✗ 'time to X' (e.g., 'time to isolation', 'time to diagnosis')\n"
            "  ✗ 'X-to-Y interval' (e.g., 'onset-to-isolation interval')\n"
            "  ✗ 'delay to X' (e.g., 'delay to isolation')\n"
            "  ✗ 'X from Y to Z' (e.g., 'time from onset to isolation')\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "📝 EXAMPLES (CORRECT vs WRONG):\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "Query: 'COVID-19 isolation delay meta-analysis'\n"
            "✓ CORRECT:\n"
            "  primary_keywords: ['COVID-19', 'SARS-CoV-2', 'isolation', 'delay', 'interval']\n"
            "  synonyms: ['2019-nCoV', 'novel coronavirus', 'quarantine', 'latency']\n"
            "  related_terms: ['symptom onset', 'transmission', 'contact tracing']\n"
            "✗ WRONG:\n"
            "  primary_keywords: ['case isolation delay', 'isolation delay interval']\n"
            "  synonyms: ['time to isolation', 'onset-to-isolation delay']\n\n"
            "Query: 'COVID-19 serial interval'\n"
            "✓ CORRECT (standardized term exists):\n"
            "  primary_keywords: ['COVID-19', 'serial interval', 'generation time']\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "🎯 META-ANALYSIS DETECTION:\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "- 'conduct/perform meta-analysis' → search PRIMARY STUDIES, NOT meta-analyses\n"
            "- design_terms: 'cohort study', 'observational study', 'surveillance'\n"
            "- Do NOT include 'meta-analysis' or 'systematic review'\n\n"
            "Format: Return ONLY valid JSON. Enforce number limits strictly."
        )
        default_user = (
            "Research Query: {research_query}\n"
            "Domain: {domain}\n\n"
            "Scoping Context (optional): {context}\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "🎯 TASK: Generate RETRIEVAL-OPTIMIZED keywords (not concept labels)\n"
            "══════════════════════════════════════════════════════════════════════\n\n"
            "STEP 1: Identify the ESTIMAND TYPE\n"
            "  - Is this a STANDARDIZED INTERVAL? (serial interval, incubation period)\n"
            "    → Use standard term as phrase\n"
            "  - Is this an OPERATIONAL DELAY? (isolation delay, testing delay, reporting delay)\n"
            "    → DECOMPOSE into atomic terms, DO NOT create compound phrases\n\n"
            "STEP 2: Extract ATOMIC TERMS (single words or standard medical terms)\n"
            "  - Disease/pathogen: COVID-19, SARS-CoV-2, influenza\n"
            "  - Time concepts: interval, delay, latency, period, duration\n"
            "  - Actions/events: isolation, quarantine, diagnosis, testing, symptom onset\n"
            "  - Epidemiological: transmission, outbreak, incidence\n\n"
            "STEP 3: Apply QUANTITY LIMITS\n"
            "  - primary_keywords: 3-5 terms\n"
            "  - synonyms: 5-8 terms\n"
            "  - related_terms: 5-10 terms\n"
            "  - other categories: 3-5 each (or empty list)\n\n"
            "STEP 4: Quality Check\n"
            "  - No 'X delay', 'time to X', 'X-to-Y' patterns\n"
            "  - No hyphens in multi-word phrases\n"
            "  - Only TRUE synonyms in synonyms list\n\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "📋 REFERENCE EXAMPLES:\n"
            "══════════════════════════════════════════════════════════════════════\n"
            "Query: 'COVID-19 isolation delay interval meta-analysis'\n"
            "✓ CORRECT OUTPUT:\n"
            "{{\n"
            '  "primary_keywords": ["COVID-19", "SARS-CoV-2", "isolation", "delay"],\n'
            '  "synonyms": ["2019-nCoV", "novel coronavirus", "quarantine", "latency", "interval"],\n'
            '  "related_terms": ["symptom onset", "diagnosis", "transmission", "contact tracing", "outbreak"],\n'
            '  "domain_terms": ["time-to-event", "survival analysis", "epidemiological investigation"],\n'
            '  "design_terms": ["cohort study", "observational study", "surveillance"]\n'
            "}}\n\n"
            "Query: 'COVID-19 serial interval meta-analysis'\n"
            "✓ CORRECT OUTPUT (standardized term):\n"
            "{{\n"
            '  "primary_keywords": ["COVID-19", "SARS-CoV-2", "serial interval"],\n'
            '  "synonyms": ["2019-nCoV", "generation time", "transmission interval"],\n'
            '  "related_terms": ["incubation period", "transmission", "infectiousness"]\n'
            "}}\n\n"
            "✗ COMMON MISTAKES TO AVOID:\n"
            '- "case isolation delay" (invented phrase, will fail in PubMed)\n'
            '- "time to isolation" (banned pattern)\n'
            '- "onset-to-isolation interval" (hyphenated compound)\n'
            "- 25 synonyms (exceeds limit, dilutes quality)\n\n"
            "Use scoping context only to extract terminology; do not copy findings or claims.\n"
            "Return ONLY valid JSON. Strictly enforce number limits."
        )
        default_refine = (
            "The following keywords were generated for this research query:\n\n"
            "Query: {research_query}\n"
            "Existing keywords: {existing_keywords}\n\n"
            "Please suggest additional relevant keywords that might have been missed. Focus on:\n"
            "- Alternative terminology\n"
            "- Related psychological constructs\n"
            "- Methodological terms\n"
            "- Population-specific terms (if applicable)\n\n"
            'Return a JSON array of additional keywords: ["keyword1", "keyword2", ...]'
        )

        prompt_path = Path(__file__).parent / "prompts" / "keyword_generator.md"
        if not prompt_path.exists():
            self._keyword_prompts = (default_system, default_user, default_refine)
            return self._keyword_prompts

        try:
            text = prompt_path.read_text(encoding="utf-8")

            def _section(tag: str) -> Optional[str]:
                match = re.search(
                    rf"\\[{tag}\\](.*?)\\[/{tag}\\]",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                return match.group(1).strip() if match else None

            system_text = _section("SYSTEM") or default_system
            user_text = _section("USER") or default_user
            refine_text = _section("REFINE") or default_refine
            self._keyword_prompts = (system_text, user_text, refine_text)
            return self._keyword_prompts
        except Exception as e:
            logger.warning("Failed to load keyword prompts: %s", e)
            self._keyword_prompts = (default_system, default_user, default_refine)
            return self._keyword_prompts

    def generate(
        self,
        research_query: str,
        domain: str = "epidemiology",
        context: Optional[str] = None,
        max_iterations: Optional[int] = None,
    ) -> KeywordSet:
        """Generate keywords for a research query.

        Args:
            research_query: The research question or topic
            domain: Psychology subdomain (optional)
            max_iterations: Override default max iterations

        Returns:
            KeywordSet with generated keywords
        """
        initial_state: KeywordGeneratorState = {
            "research_query": research_query,
            "domain": domain,
            "context": context,
            "keywords": None,
            "iteration": 0,
            "max_iterations": max_iterations or self.max_iterations,
            "error": None,
        }

        # Run agent
        final_state = self.agent.invoke(initial_state)

        keywords = final_state.get("keywords")
        if keywords is None:
            # Fallback: create minimal keyword set
            keywords = KeywordSet(
                primary_keywords=[research_query],
                synonyms=[],
                related_terms=[],
                domain_terms=[],
                search_queries=[research_query],
            )

        return keywords

    def generate_batch(
        self,
        research_queries: List[str],
        domain: str = "epidemiology",
    ) -> List[KeywordSet]:
        """Generate keywords for multiple queries.

        Args:
            research_queries: List of research questions
            domain: Epidemiology subdomain

        Returns:
            List of KeywordSet objects
        """
        results = []
        for query in research_queries:
            try:
                keywords = self.generate(query, domain=domain)
                results.append(keywords)
            except Exception as e:
                logger.error(f"Error generating keywords for '{query}': {e}")
                # Add fallback
                results.append(
                    KeywordSet(
                        primary_keywords=[query],
                        synonyms=[],
                        related_terms=[],
                        domain_terms=[],
                        search_queries=[query],
                    )
                )
        return results


def example_usage():
    """Example usage of keyword generator."""
    # Initialize agent
    agent = KeywordGeneratorAgent(
        llm_provider="claude",
        temperature=0.7,
    )

    # Generate keywords
    query = "What is the effectiveness of cognitive behavioral therapy for anxiety disorders?"
    keywords = agent.generate(query, domain="clinical_psychology")

    print(f"\nResearch Query: {query}")
    print(f"\nPrimary Keywords: {keywords.primary_keywords}")
    print(f"Synonyms: {keywords.synonyms}")
    print(f"Related Terms: {keywords.related_terms}")
    print(f"Domain Terms: {keywords.domain_terms}")
    print(f"\nSearch Queries: {keywords.search_queries}")

    return keywords


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_usage()
