import copy
from typing import Any, Literal, Self

from pydantic import Field

from conduit.protocol.base import (
    PROTOCOL_VERSION,
    Notification,
    ProtocolModel,
    Request,
    Result,
)


class RootsCapability(ProtocolModel):
    """
    Capability for listing and monitoring filesystem roots.
    """

    list_changed: bool | None = Field(default=None, alias="listChanged")
    """
    Whether the client sends notifications when roots change.
    """


class Implementation(ProtocolModel):
    """Name and version string of the server or client."""

    name: str
    version: str


class ClientCapabilities(ProtocolModel):
    """
    Capabilities that the client supports. Sent during initialization.
    """

    experimental: dict[str, Any] | None = None
    """
    Experimental or non-standard capabilities.
    """

    roots: RootsCapability | None = None
    """
    Filesystem roots listing and monitoring.
    """

    sampling: bool = False
    """
    LLM sampling support from the host.
    """


class PromptsCapability(ProtocolModel):
    """Capabilities for prompt management and notifications."""

    list_changed: bool | None = Field(default=None, alias="listChanged")
    """
    Whether the server sends notifications when prompts change.
    """


class ResourcesCapability(ProtocolModel):
    """Capabilities for resource access and change monitoring."""

    subscribe: bool | None = None
    """
    Whether clients can subscribe to resource change updates.
    """

    list_changed: bool | None = Field(default=None, alias="listChanged")
    """
    Whether the server sends notifications when resources change.
    """


class ToolsCapability(ProtocolModel):
    """Capabilities for tool execution and change notifications."""

    list_changed: bool | None = Field(default=None, alias="listChanged")
    """
    Whether the server sends notifications when tools change.
    """


class ServerCapabilities(ProtocolModel):
    """Capabilities that the server supports, sent during initialization."""

    experimental: dict[str, Any] | None = None
    """
    Experimental or non-standard capabilities.
    """
    logging: dict[str, Any] | None = None
    """
    Loggin capability configuration.
    """
    completions: dict[str, Any] | None = None
    """
    Completion capabilities.
    """
    prompts: PromptsCapability | None = None
    """
    Prompt management capabilities.
    """
    resources: ResourcesCapability | None = None
    """
    Resource access capabilities.
    """
    tools: ToolsCapability | None = None
    """
    Tool execution capabilities.
    """


# --------- Initialization Types ----------


class InitializedNotification(Notification):
    """
    Confirms successful MCP connection initialization.

    Sent by the client after processing the server's InitializeResult.
    """

    method: Literal["notifications/initialized"] = "notifications/initialized"


class InitializeResult(Result):
    """
    Server's response to initialization, completing the MCP handshake.

    Contains server capabilities and optional setup instructions for the client.
    """

    protocol_version: str = Field(default=PROTOCOL_VERSION, alias="protocolVersion")
    capabilities: ServerCapabilities
    """
    Capabilities the server supports.
    """

    server_info: Implementation = Field(alias="serverInfo")
    """
    Information about the server software.
    """

    instructions: str | None = None
    """
    Optional setup or usage instructions for the client.
    """


class InitializeRequest(Request):
    """
    Initial handshake request to establish MCP connection.

    Sent by the client to negotiate protocol version and exchange capability
    information.
    """

    method: Literal["initialize"] = "initialize"
    protocol_version: str = Field(
        default=PROTOCOL_VERSION, alias="protocolVersion", frozen=True
    )
    client_info: Implementation = Field(alias="clientInfo")
    """
    Information about the client software.
    """

    capabilities: ClientCapabilities = Field(default_factory=ClientCapabilities)
    """
    Capabilities the client supports.
    """

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Convert from protocol-level representation.

        Note: Deviates from MCP spec for better usability. The spec defines sampling
        as dict[str, Any] | None, but we convert any non-null value to True since
        sampling has no sub-options. This makes capability checking cleaner. Run
        `if capabilities.sampling` instead of `if capabilities.sampling is not None`.

        - Wire format: {"capabilities": {"sampling": {}}}
        - Python API:  {"capabilities": {"sampling": True}} (or False)
        """
        data = copy.deepcopy(data)
        if "params" in data and "capabilities" in data["params"]:
            capabilities = data["params"]["capabilities"]
            if "sampling" in capabilities:
                capabilities["sampling"] = True

        return super().from_protocol(data)

    def to_protocol(self) -> dict[str, Any]:
        """Convert to protocol-level representation.

        Converts our boolean sampling capability back to the spec format:
        - sampling=True becomes {"sampling": {}}
        - sampling=False omits the sampling field entirely

        This ensures wire compatibility while maintaining clean Python APIs.
        """
        result = super().to_protocol()
        params = result["params"]
        if self.capabilities.sampling:
            params["capabilities"]["sampling"] = {}
        else:
            del params["capabilities"]["sampling"]
        return result

    @classmethod
    def expected_result_type(cls) -> type[InitializeResult]:
        return InitializeResult
