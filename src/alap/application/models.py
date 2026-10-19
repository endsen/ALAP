"""Versioned model configuration and provider-independent application port.

Tools in a request must already be authorized by the application. A completed
proposal is data, never permission to execute an experiment or device command.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from threading import Event
from typing import Literal, Protocol

CapabilityStatus = Literal["declared", "tested", "unsupported", "unknown"]


@dataclass(frozen=True)
class Capabilities:
    streaming: CapabilityStatus = "unknown"
    tools: CapabilityStatus = "unknown"
    structured: CapabilityStatus = "unknown"
    vision: CapabilityStatus = "unsupported"
    usage: CapabilityStatus = "unknown"


@dataclass(frozen=True)
class ProviderConnection:
    id: str
    version: int
    vendor: Literal["openai", "deepseek"]
    base_url: str
    secret_ref: str = field(repr=False)
    protocol: str = "chat-completions-v1"
    enabled: bool = True
    network_policy: str = "official-https-only"


@dataclass(frozen=True)
class ModelProfile:
    id: str
    version: int
    connection_id: str
    connection_version: int
    model: str
    context_tokens: int
    output_tokens: int
    capabilities: Capabilities
    timeout_seconds: float = 30
    max_attempts: int = 1
    temperature: float | None = None
    price_reference: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    # Serialized schemas avoid mutable configuration behind a frozen profile.
    schema_json: str


@dataclass(frozen=True)
class ToolCallMessage:
    id: str
    name: str
    arguments_json: str


@dataclass(frozen=True)
class ModelMessage:
    role: str
    content: str
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCallMessage, ...] = ()


@dataclass(frozen=True)
class ModelRequest:
    messages: tuple[tuple[str, str] | ModelMessage, ...]
    trace_id: str
    tools: tuple[ToolDefinition, ...] = ()
    output_schema_json: str | None = None
    # Explicit JSON-object mode plus local schema validation, not server strict mode.
    json_object_mode: bool = False
    total_seconds: float = 60
    # Conservative per-attempt input+output reservation; unknown usage isn't zero.
    token_budget: int = 8192
    max_response_bytes: int = 1_048_576


@dataclass(frozen=True)
class ModelEvent:
    kind: Literal["text_delta", "tool_call_delta", "usage", "finish", "error", "attempt"]
    trace_id: str
    attempt_id: str
    vendor: str
    model: str
    data: Mapping[str, object]


class SecretStore(Protocol):
    def resolve(self, reference: str) -> str: ...


class ModelClient(Protocol):
    def stream(
        self, request: ModelRequest, cancel: Event | None = None
    ) -> Iterator[ModelEvent]: ...
