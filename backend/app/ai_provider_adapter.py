from __future__ import annotations

import json
import logging
import threading
import time
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import httpx
from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError
from sqlalchemy import text
from sqlalchemy.orm import Session

LOGGER = logging.getLogger(__name__)

TRANSIENT_EXCEPTIONS = (
    TimeoutError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    ConnectTimeoutError,
    ReadTimeoutError,
    EndpointConnectionError,
)

PROVIDER_ALIASES = {
    "google_ai_studio": "gemini",
    "google": "gemini",
    "google_gemini": "gemini",
    "azure": "azure_openai",
    "aws": "aws_bedrock",
    "bedrock": "aws_bedrock",
    "deepseek_vl": "deepseek",
    "nvidia": "nvidia_nim",
    "cerebras_systems": "cerebras",
    "together_ai": "together",
    "fireworks": "fireworks_ai",
    "hf": "huggingface",
    "hugging_face": "huggingface",
    "aiml": "aimlapi",
    "novita_ai": "novita",
    "base64": "base64_ai",
}

DEFAULT_ROUTES: dict[str, tuple[str, ...]] = {
    "vision_form_reading": ("gemini", "groq", "anthropic", "openrouter"),
    "document_processing": ("base64_ai", "azure_document_intelligence", "aws_bedrock", "gemini"),
    "semantic_analysis": ("anthropic", "openai", "gemini", "mistral", "cohere"),
    "general": ("openai", "anthropic", "gemini", "groq", "openrouter"),
}


class AIProviderError(RuntimeError):
    """Base error for adapter/provider failures."""


class AIProviderUnavailable(AIProviderError):
    """Provider SDK is not installed or provider configuration is missing."""


class AIProviderExhausted(AIProviderError):
    """Every provider in the selected route failed before the deadline."""


@dataclass(frozen=True)
class AIRequest:
    task: str
    model: str
    messages: Sequence[Mapping[str, Any]]
    response_format: Mapping[str, Any] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    provider_route: Sequence[str] | None = None
    timeout_seconds: float = 0.75
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIProviderResult:
    provider: str
    model: str
    text: str
    form_tokens: Mapping[str, Any] | None
    usage: Mapping[str, Any]
    latency_ms: int
    raw: Any = None


@dataclass(frozen=True)
class ProviderCredentials:
    provider: str
    payload: Any


class MultiAIProviderAdapter:
    """Thread-safe native multi-provider AI adapter with database-locked credential loading.

    This layer is intentionally capability-limited to AI inference/document analysis. It never
    receives a browser page handle and never contains form-submit/DOM mutation operations.
    """

    def __init__(
        self,
        db: Session,
        *,
        credential_decryptor: Callable[[Any], Any],
        routes: Mapping[str, Sequence[str]] | None = None,
        audit_sink: Callable[[Mapping[str, Any]], None] | None = None,
        failover_budget_seconds: float = 1.8,
        http_client_factory: Callable[..., httpx.Client] | None = None,
    ) -> None:
        if failover_budget_seconds <= 0 or failover_budget_seconds >= 2.0:
            raise ValueError("failover_budget_seconds must be > 0 and < 2 seconds")
        self.db = db
        self.credential_decryptor = credential_decryptor
        self.routes = {**DEFAULT_ROUTES, **(routes or {})}
        self.audit_sink = audit_sink or self._default_audit_sink
        self.failover_budget_seconds = failover_budget_seconds
        self._http_client_factory = http_client_factory or httpx.Client
        self._lock = threading.RLock()

    def execute(self, request: AIRequest) -> AIProviderResult:
        providers = tuple(request.provider_route or self.routes.get(request.task, self.routes["general"]))
        if not providers:
            raise ValueError("at least one provider is required")

        started = time.monotonic()
        deadline = started + min(self.failover_budget_seconds, request.timeout_seconds * max(1, len(providers)))
        failures: list[tuple[str, Exception]] = []
        request_id = str(request.metadata.get("request_id") or uuid4())
        user_id = request.metadata.get("user_id")
        task_id = request.metadata.get("task_id")
        if user_id:
            self._enforce_quota(str(user_id))

        for provider_name in providers:
            if time.monotonic() >= deadline:
                break
            provider = self._canonical_provider(provider_name)
            provider_started = time.monotonic()
            try:
                if request.metadata.get("user_id") and not self._provider_allowed(provider, request):
                    continue
                credentials = self._load_credentials(provider)
                result = self._dispatch(provider, request, credentials, max(0.1, min(request.timeout_seconds, deadline - time.monotonic())))
                latency_ms = self._elapsed_ms(provider_started)
                self._record_usage(request, request_id, result, latency_ms, "success", fallback_from=failures[-1][0] if failures else None)
                if request.metadata.get("user_id"):
                    self._record_provider_health(provider, success=True)
                self._audit("provider.success", provider=provider, task=request.task, model=request.model, latency_ms=latency_ms)
                return result
            except Exception as exc:  # deliberate boundary around third-party SDKs
                failures.append((provider, exc))
                transient = self._is_transient(exc)
                self._record_usage(request, request_id, AIProviderResult(provider, request.model, "", {}, {}, self._elapsed_ms(provider_started)), self._elapsed_ms(provider_started), "failure", error_type=type(exc).__name__)
                if request.metadata.get("user_id"):
                    self._record_provider_health(provider, success=False)
                self._audit(
                    "provider.failure",
                    provider=provider,
                    task=request.task,
                    model=request.model,
                    transient=transient,
                    error_type=type(exc).__name__,
                    latency_ms=self._elapsed_ms(provider_started),
                )
                if not transient:
                    raise AIProviderError(f"non-transient failure from {provider}") from exc

        summary = ", ".join(f"{provider}:{type(exc).__name__}" for provider, exc in failures) or "no provider attempted"
        raise AIProviderExhausted(f"AI failover exhausted within budget: {summary}")

    def _provider_allowed(self, provider: str, request: AIRequest) -> bool:
        """Apply administrator policy and database-backed rate/cooldown limits."""
        try:
            policy = self.db.execute(text("SELECT enabled, daily_tokens, monthly_tokens, daily_cost, monthly_cost, requests_per_minute, cooldown_seconds FROM ai_provider_policy WHERE provider = :provider"), {"provider": provider}).mappings().first()
            if not policy:
                return True
            if not policy["enabled"]:
                return False
            health = self.db.execute(text("SELECT cooldown_until FROM ai_provider_health WHERE provider = :provider"), {"provider": provider}).mappings().first()
            if health and health["cooldown_until"]:
                return False
            user_id = str(request.metadata["user_id"])
            usage = self.db.execute(text("""
                SELECT COALESCE(SUM(total_tokens),0) tokens, COALESCE(SUM(estimated_cost),0) cost,
                       COUNT(*) FILTER (WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '1 minute') requests
                FROM ai_usage_ledger WHERE provider=:provider AND user_id=:user_id
                AND created_at >= CURRENT_TIMESTAMP - INTERVAL '1 month'
            """), {"provider": provider, "user_id": user_id}).mappings().first()
            if policy["requests_per_minute"] and int(usage["requests"] or 0) >= int(policy["requests_per_minute"]):
                return False
            if policy["monthly_tokens"] and int(usage["tokens"] or 0) >= int(policy["monthly_tokens"]):
                return False
            if policy["monthly_cost"] and float(usage["cost"] or 0) >= float(policy["monthly_cost"]):
                return False
            return True
        except AIProviderError:
            raise
        except Exception:
            LOGGER.debug("AI provider policy lookup unavailable", exc_info=True)
            return True

    def _record_provider_health(self, provider: str, *, success: bool) -> None:
        try:
            if success:
                self.db.execute(text("""
                    INSERT INTO ai_provider_health(provider,status,request_count,last_success_at,updated_at)
                    VALUES (:provider,'healthy',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT (provider) DO UPDATE SET status='healthy', request_count=ai_provider_health.request_count+1, last_success_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                """), {"provider": provider})
            else:
                self.db.execute(text("""
                    INSERT INTO ai_provider_health(provider,status,error_count,request_count,last_failure_at,updated_at)
                    VALUES (:provider,'degraded',1,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT (provider) DO UPDATE SET status='degraded', error_count=ai_provider_health.error_count+1, request_count=ai_provider_health.request_count+1, error_rate=(ai_provider_health.error_count+1)::numeric/(ai_provider_health.request_count+1), last_failure_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP
                """), {"provider": provider})
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _enforce_quota(self, user_id: str) -> None:
        """Apply database-backed user and global budget limits before an AI call."""
        try:
            row = self.db.execute(text("""
                SELECT COALESCE(SUM(total_tokens), 0) AS tokens, COALESCE(SUM(estimated_cost), 0) AS cost
                FROM ai_usage_ledger WHERE user_id = :user_id AND created_at >= CURRENT_TIMESTAMP - INTERVAL '1 day'
            """), {"user_id": user_id}).mappings().first()
            if row and int(row["tokens"] or 0) >= 100_000:
                raise AIProviderError("daily AI token quota exceeded")
            if row and float(row["cost"] or 0) >= 25:
                raise AIProviderError("daily AI budget exceeded")
        except AIProviderError:
            raise
        except Exception:
            # Local test databases may not have the production ledger yet; provider execution remains usable.
            LOGGER.debug("AI quota lookup unavailable", exc_info=True)

    def _record_usage(self, request: AIRequest, request_id: str, result: AIProviderResult, latency_ms: int, status: str, *, fallback_from: str | None = None, error_type: str | None = None) -> None:
        if not request.metadata.get("user_id"):
            return
        usage = result.usage or {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        estimated_cost = float(request.metadata.get("estimated_cost_per_1k", 0)) * total_tokens / 1000
        try:
            self.db.execute(text("""
                INSERT INTO ai_usage_ledger
                (usage_id, provider, model, request_id, task_name, user_id, task_id, input_tokens, output_tokens, total_tokens, latency_ms, status, fallback_from, estimated_cost, error_type, created_at)
                VALUES (:usage_id, :provider, :model, :request_id, :task_name, :user_id, :task_id, :input_tokens, :output_tokens, :total_tokens, :latency_ms, :status, :fallback_from, :estimated_cost, :error_type, CURRENT_TIMESTAMP)
            """), {"usage_id": str(uuid4()), "provider": result.provider, "model": result.model, "request_id": request_id, "task_name": request.task, "user_id": str(request.metadata.get("user_id")), "task_id": request.metadata.get("task_id"), "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens, "latency_ms": latency_ms, "status": status, "fallback_from": fallback_from, "estimated_cost": estimated_cost, "error_type": error_type})
            self.db.commit()
        except Exception:
            self.db.rollback()
            LOGGER.exception("AI usage ledger write failed")

    def _load_credentials(self, provider: str) -> ProviderCredentials:
        # PostgreSQL/Supabase path uses FOR UPDATE as required. SQLite accepts the same query
        # syntax only on PostgreSQL, so the adapter falls back to a normal row read locally.
        dialect = getattr(getattr(self.db, "bind", None), "dialect", None)
        dialect_name = getattr(dialect, "name", "")
        query = "SELECT provider_name, api_key_encrypted, is_active FROM admin_api_keys WHERE provider_name = :provider"
        if dialect_name == "postgresql":
            query += " FOR UPDATE"
        row = self.db.execute(text(query), {"provider": provider}).mappings().first()
        if not row or not row["is_active"]:
            raise AIProviderUnavailable(f"no active credential configured for {provider}")
        payload = self.credential_decryptor(row["api_key_encrypted"])
        if payload is None or payload == "":
            raise AIProviderUnavailable(f"decrypted credential is empty for {provider}")
        return ProviderCredentials(provider=provider, payload=payload)

    def _dispatch(self, provider: str, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        with self._lock:
            handlers = {
                "gemini": self._gemini,
                "openai": self._openai,
                "anthropic": self._anthropic,
                "azure_openai": self._azure_openai,
                "aws_bedrock": self._bedrock,
                "groq": self._groq,
                "deepseek": self._openai_compatible,
                "nvidia_nim": self._openai_compatible,
                "cerebras": self._cerebras,
                "together": self._together,
                "fireworks_ai": self._fireworks,
                "lepton": self._lepton,
                "openrouter": self._openai_compatible,
                "huggingface": self._huggingface,
                "aimlapi": self._openai_compatible,
                "novita": self._openai_compatible,
                "perplexity": self._openai_compatible,
                "cohere": self._cohere,
                "mistral": self._mistral,
                "base64_ai": self._base64_ai,
            }
            handler = handlers.get(provider)
            if handler is None:
                return self._openai_compatible(request, credentials, timeout, provider=provider)
            return handler(request, credentials, timeout)

    def _gemini(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from google import genai
        except ImportError as exc:
            raise AIProviderUnavailable("google-genai is not installed") from exc
        client = genai.Client(api_key=str(credentials.payload))
        prompt = self._messages_to_prompt(request.messages)
        response = client.models.generate_content(model=request.model, contents=prompt)
        text_value = getattr(response, "text", "") or ""
        usage = self._usage(response)
        return self._result("gemini", request.model, text_value, usage, response)

    def _openai(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AIProviderUnavailable("openai is not installed") from exc
        client = OpenAI(api_key=str(credentials.payload), timeout=timeout, max_retries=0)
        response = client.responses.create(model=request.model, input=self._messages_to_openai_input(request.messages))
        text_value = getattr(response, "output_text", "") or ""
        return self._result("openai", request.model, text_value, self._usage(response), response)

    def _anthropic(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise AIProviderUnavailable("anthropic is not installed") from exc
        client = Anthropic(api_key=str(credentials.payload), timeout=timeout, max_retries=0)
        system, messages = self._split_system(request.messages)
        response = client.messages.create(model=request.model, max_tokens=request.max_tokens or 1024, system=system or None, messages=messages)
        parts = getattr(response, "content", [])
        text_value = "".join(getattr(part, "text", "") for part in parts)
        return self._result("anthropic", request.model, text_value, self._usage(response), response)

    def _azure_openai(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise AIProviderUnavailable("openai is not installed") from exc
        config = self._mapping(credentials.payload)
        client = AzureOpenAI(api_key=config["api_key"], azure_endpoint=config["azure_endpoint"], api_version=config.get("api_version", "2024-10-21"), timeout=timeout, max_retries=0)
        deployment = config.get("deployment") or request.model
        response = client.responses.create(model=deployment, input=self._messages_to_openai_input(request.messages))
        return self._result("azure_openai", deployment, getattr(response, "output_text", "") or "", self._usage(response), response)

    def _bedrock(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        import boto3
        config = self._mapping(credentials.payload)
        client = boto3.client("bedrock-runtime", region_name=config.get("region", "us-east-1"), aws_access_key_id=config.get("access_key_id"), aws_secret_access_key=config.get("secret_access_key"))
        body = {"messages": list(request.messages), "max_tokens": request.max_tokens or 1024, "temperature": request.temperature or 0}
        response = client.converse(modelId=request.model, messages=list(request.messages), inferenceConfig={"maxTokens": body["max_tokens"], "temperature": body["temperature"]})
        content = response.get("output", {}).get("message", {}).get("content", [])
        text_value = "".join(item.get("text", "") for item in content if isinstance(item, Mapping))
        return self._result("aws_bedrock", request.model, text_value, response.get("usage", {}), response)

    def _groq(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from groq import Groq
        except ImportError as exc:
            raise AIProviderUnavailable("groq is not installed") from exc
        client = Groq(api_key=str(credentials.payload), timeout=timeout, max_retries=0)
        response = client.chat.completions.create(model=request.model, messages=list(request.messages), temperature=request.temperature)
        message = response.choices[0].message
        return self._result("groq", request.model, getattr(message, "content", "") or "", self._usage(response), response)

    def _cerebras(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from cerebras.cloud.sdk import Cerebras
        except ImportError as exc:
            raise AIProviderUnavailable("cerebras-cloud-sdk is not installed") from exc
        client = Cerebras(api_key=str(credentials.payload), timeout=timeout, max_retries=0)
        response = client.chat.completions.create(model=request.model, messages=list(request.messages), temperature=request.temperature)
        return self._result("cerebras", request.model, response.choices[0].message.content or "", self._usage(response), response)

    def _together(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from together import Together
        except ImportError as exc:
            raise AIProviderUnavailable("together is not installed") from exc
        client = Together(api_key=str(credentials.payload))
        response = client.chat.completions.create(model=request.model, messages=list(request.messages), temperature=request.temperature)
        return self._result("together", request.model, response.choices[0].message.content or "", self._usage(response), response)

    def _fireworks(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from fireworks.client import Fireworks
        except ImportError as exc:
            raise AIProviderUnavailable("fireworks-ai is not installed") from exc
        client = Fireworks(api_key=str(credentials.payload), timeout=timeout)
        response = client.chat.completions.create(model=request.model, messages=list(request.messages), temperature=request.temperature)
        return self._result("fireworks_ai", request.model, response.choices[0].message.content or "", self._usage(response), response)

    def _lepton(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        config = self._mapping(credentials.payload)
        return self._openai_compatible(request, ProviderCredentials(request.provider, config), timeout, provider="lepton")

    def _huggingface(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from huggingface_hub import InferenceClient
        except ImportError as exc:
            raise AIProviderUnavailable("huggingface_hub is not installed") from exc
        client = InferenceClient(token=str(credentials.payload), timeout=timeout)
        response = client.chat_completion(model=request.model, messages=list(request.messages), temperature=request.temperature)
        return self._result("huggingface", request.model, response.choices[0].message.content or "", self._usage(response), response)

    def _cohere(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            import cohere
        except ImportError as exc:
            raise AIProviderUnavailable("cohere is not installed") from exc
        client = cohere.ClientV2(api_key=str(credentials.payload), timeout=timeout)
        response = client.chat(model=request.model, messages=list(request.messages), temperature=request.temperature)
        content = getattr(response.message, "content", [])
        text_value = "".join(getattr(item, "text", "") for item in content)
        return self._result("cohere", request.model, text_value, self._usage(response), response)

    def _mistral(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        try:
            from mistralai import Mistral
        except ImportError as exc:
            raise AIProviderUnavailable("mistralai is not installed") from exc
        client = Mistral(api_key=str(credentials.payload))
        response = client.chat.complete(model=request.model, messages=list(request.messages), temperature=request.temperature)
        return self._result("mistral", request.model, response.choices[0].message.content or "", self._usage(response), response)

    def _base64_ai(self, request: AIRequest, credentials: ProviderCredentials, timeout: float) -> AIProviderResult:
        config = self._mapping(credentials.payload)
        if "url" not in config:
            raise AIProviderUnavailable("base64_ai requires a url in its decrypted credential payload")
        body = {"model": request.model, "messages": list(request.messages)}
        response = self._http_json(config["url"], str(config["api_key"]), body, timeout)
        text_value = self._extract_text(response)
        return self._result("base64_ai", request.model, text_value, response.get("usage", {}), response)

    def _openai_compatible(self, request: AIRequest, credentials: ProviderCredentials, timeout: float, provider: str) -> AIProviderResult:
        config = self._mapping(credentials.payload)
        base_url = str(config.get("base_url", "")).rstrip("/")
        api_key = str(config.get("api_key", credentials.payload if isinstance(credentials.payload, str) else ""))
        if not base_url:
            defaults = {
                "deepseek": "https://api.deepseek.com",
                "nvidia_nim": "https://integrate.api.nvidia.com/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "aimlapi": "https://api.aimlapi.com/v1",
                "novita": "https://api.novita.ai/openai/v1",
                "perplexity": "https://api.perplexity.ai",
                "lepton": "https://llama-api.lepton.run/api/v1",
            }
            base_url = defaults.get(provider, "")
        if not base_url or not api_key:
            raise AIProviderUnavailable(f"{provider} requires api_key and base_url configuration")
        response = self._http_json(
            f"{base_url}/chat/completions",
            api_key,
            {"model": request.model, "messages": list(request.messages), "temperature": request.temperature},
            timeout,
            headers=self._provider_headers(provider),
        )
        text_value = self._extract_text(response)
        return self._result(provider, request.model, text_value, response.get("usage", {}), response)

    def _http_json(self, url: str, api_key: str, body: Mapping[str, Any], timeout: float, headers: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        request_headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", **(headers or {})}
        with self._http_client_factory(timeout=timeout) as client:
            response = client.post(url, headers=request_headers, json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, Mapping):
                raise AIProviderError("provider returned a non-object JSON response")
            return payload

    def _provider_headers(self, provider: str) -> Mapping[str, str]:
        if provider == "openrouter":
            return {"HTTP-Referer": "https://formwise.ai", "X-Title": "Formwise Unified AI Engine"}
        return {}

    def _result(self, provider: str, model: str, text_value: str, usage: Mapping[str, Any], raw: Any) -> AIProviderResult:
        return AIProviderResult(provider=provider, model=model, text=text_value, form_tokens=self._parse_form_tokens(text_value), usage=dict(usage or {}), latency_ms=0, raw=raw)

    @staticmethod
    def _parse_form_tokens(value: str) -> Mapping[str, Any] | None:
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
        if isinstance(parsed, Mapping) and isinstance(parsed.get("form_tokens"), Mapping):
            return parsed["form_tokens"]
        return None

    @staticmethod
    def _messages_to_prompt(messages: Sequence[Mapping[str, Any]]) -> str:
        chunks: list[str] = []
        for message in messages:
            chunks.append(f"{message.get('role', 'user')}: {message.get('content', '')}")
        return "\n".join(chunks)

    @staticmethod
    def _messages_to_openai_input(messages: Sequence[Mapping[str, Any]]) -> Any:
        return list(messages)

    @staticmethod
    def _split_system(messages: Sequence[Mapping[str, Any]]) -> tuple[str, list[Mapping[str, Any]]]:
        system_parts = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
        rest = [m for m in messages if m.get("role") != "system"]
        return "\n".join(system_parts), rest

    @staticmethod
    def _mapping(payload: Any) -> Mapping[str, Any]:
        if isinstance(payload, Mapping):
            return payload
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
                if isinstance(decoded, Mapping):
                    return decoded
            except json.JSONDecodeError:
                return {"api_key": payload}
        raise AIProviderUnavailable("decrypted credential payload must be a string or mapping")

    @staticmethod
    def _extract_text(response: Mapping[str, Any]) -> str:
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content", "") if isinstance(message, Mapping) else ""
            return str(content or "")
        return str(response.get("text", "") or "")

    @staticmethod
    def _usage(response: Any) -> Mapping[str, Any]:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, Mapping):
            usage = response.get("usage")
        if usage is None:
            return {}
        if isinstance(usage, Mapping):
            return usage
        return {key: getattr(usage, key) for key in ("prompt_tokens", "completion_tokens", "total_tokens") if hasattr(usage, key)}

    @staticmethod
    def _canonical_provider(provider: str) -> str:
        normalized = provider.strip().lower().replace("-", "_").replace(" ", "_")
        return PROVIDER_ALIASES.get(normalized, normalized)

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        if isinstance(exc, TRANSIENT_EXCEPTIONS):
            return True
        if isinstance(exc, (ClientError, httpx.HTTPStatusError)):
            if isinstance(exc, ClientError):
                status = (exc.response or {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            else:
                status = exc.response.status_code
            return status == 429 or status is None or int(status) >= 500
        name = type(exc).__name__.lower()
        return "ratelimit" in name or "rate_limit" in name or name.endswith("timeout")

    def _audit(self, event: str, **fields: Any) -> None:
        payload = {"event": event, "timestamp": time.time(), **fields}
        try:
            self.audit_sink(payload)
        except Exception:
            LOGGER.exception("AI audit sink failure")

    @staticmethod
    def _default_audit_sink(payload: Mapping[str, Any]) -> None:
        LOGGER.info("formwise.ai_audit %s", json.dumps(payload, sort_keys=True, default=str))

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)
