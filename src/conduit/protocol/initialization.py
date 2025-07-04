import copy
from typing import Any, Literal, Self

from pydantic import Field

from conduit.protocol.base import (
    PROTOCOL_VERSION,
    BaseMetadata,
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


class Implementation(BaseMetadata):
    """Name and version string of the server or client."""

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

    elicitation: bool = False
    """
    Whether the client supports elicitation.
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

    logging: bool = False
    """
    Logging capability configuration.
    """

    completions: bool = False
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

        We simplify the sampling capability from the spec's `dict | None` format
        to a clean boolean. Since sampling has no configuration options, this
        makes capability checking more intuitive: `if capabilities.sampling`
        instead of `if capabilities.sampling is not None`.

        Wire format: {"capabilities": {"sampling": {}}}
        Python API:  {"capabilities": {"sampling": True}}
        """
        # Create a mutable copy to transform sampling capability
        transformed_data = copy.deepcopy(data)

        # Convert sampling from dict to boolean if present
        params = transformed_data.get("params", {})
        capabilities = params.get("capabilities", {})
        if "sampling" in capabilities:
            transformed_data["params"]["capabilities"]["sampling"] = True

        if "elicitation" in capabilities:
            transformed_data["params"]["capabilities"]["elicitation"] = True

        return super().from_protocol(transformed_data)

    def to_protocol(self) -> dict[str, Any]:
        """Convert to protocol-level representation.

        Translates our boolean sampling flag back to the spec's format:
        True becomes {"sampling": {}}, False omits the field entirely.
        This maintains wire compatibility while keeping the Python API clean.
        """
        result = super().to_protocol()
        params = result["params"]

        # Handle sampling capability
        if self.capabilities.sampling:
            params["capabilities"]["sampling"] = {}
        else:
            params["capabilities"].pop("sampling", None)

        # Handle elicitation capability
        if self.capabilities.elicitation:
            params["capabilities"]["elicitation"] = {}
        else:
            params["capabilities"].pop("elicitation", None)

        return result

    @classmethod
    def expected_result_type(cls) -> type["InitializeResult"]:
        return InitializeResult


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

    @classmethod
    def from_protocol(cls, data: dict[str, Any]) -> Self:
        """Convert from protocol-level representation.

        We simplify the logging and completions capabilities from the spec's
        `dict | None` format to clean booleans. Since these capabilities have
        no configuration options, this makes capability checking more intuitive:
        `if capabilities.logging` instead of `if capabilities.logging is not None`.

        Wire format: {"capabilities": {"logging": {}, "completions": {}}}
        Python API:  {"capabilities": {"logging": True, "completions": True}}
        """
        # Create a mutable copy to transform capabilities
        transformed_data = copy.deepcopy(data)

        # Convert capabilities from dict to boolean if present
        result_data = transformed_data.get("result", {})
        capabilities = result_data.get("capabilities", {})

        if "logging" in capabilities:
            transformed_data["result"]["capabilities"]["logging"] = True

        if "completions" in capabilities:
            transformed_data["result"]["capabilities"]["completions"] = True

        return super().from_protocol(transformed_data)

    def to_protocol(self) -> dict[str, Any]:
        """Convert to protocol-level representation.

        Translates our boolean capability flags back to the spec's format:
        True becomes {"logging": {}}, False omits the field entirely.
        This maintains wire compatibility while keeping the Python API clean.
        """
        # Get the base result data
        result = super().to_protocol()

        # Handle logging capability
        if self.capabilities.logging:
            result["capabilities"]["logging"] = {}
        else:
            result["capabilities"].pop("logging", None)

        # Handle completions capability
        if self.capabilities.completions:
            result["capabilities"]["completions"] = {}
        else:
            result["capabilities"].pop("completions", None)

        return result
