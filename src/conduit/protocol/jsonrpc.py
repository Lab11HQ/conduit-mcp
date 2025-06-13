from typing import Any

from pydantic import Field

from conduit.protocol.base import (
    Error,
    Notification,
    ProtocolModel,
    Request,
    RequestId,
    Result,
)

JSONRPC_VERSION = "2.0"


class JSONRPCRequest(ProtocolModel):
    """
    JSON-RPC 2.0 request wrapper for MCP requests.

    Wire format for requests that expect responses.
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, frozen=True)
    id: RequestId
    """
    Unique identifier for matching requests to responses. String or integer.
    """

    request: Request
    """
    The MCP request payload.
    """

    @classmethod
    def from_request(cls, request: Request, id: RequestId) -> "JSONRPCRequest":
        """Convert from Request to JSONRPCRequest"""
        return cls(id=id, request=request)

    def to_request(self) -> Request:
        """Convert back to a Request object"""
        return self.request

    def to_wire(self) -> dict[str, Any]:
        """Convert to wire format (spec-compliant JSON-RPC 2.0)"""
        protocol_data = self.request.to_protocol()
        protocol_data["jsonrpc"] = self.jsonrpc
        protocol_data["id"] = self.id
        return protocol_data


class JSONRPCNotification(ProtocolModel):
    """
    JSON-RPC 2.0 notification wrapper for MCP notifications.

    Wire format for one-way messages that don't expect responses.
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, frozen=True)
    notification: Notification
    """
    The actual MCP notification payload.
    """

    @classmethod
    def from_notification(cls, notification: Notification) -> "JSONRPCNotification":
        return cls(notification=notification)

    def to_notification(self) -> Notification:
        return self.notification

    def to_wire(self) -> dict[str, Any]:
        """Convert to wire format (spec-compliant JSON-RPC 2.0)"""
        protocol_data = self.notification.to_protocol()
        protocol_data["jsonrpc"] = self.jsonrpc
        return protocol_data


class JSONRPCResponse(ProtocolModel):
    """
    JSON-RPC 2.0 response wrapper for successful MCP results.

    Wire format for successful request responses.
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, frozen=True)
    id: RequestId
    """
    Identifier matching the original request.
    """

    result: Result
    """
    MCP result payload.
    """

    @classmethod
    def from_result(cls, result: Result, id: RequestId) -> "JSONRPCResponse":
        """Convert from Result to JSONRPCResponse"""
        return cls(id=id, result=result)

    def to_result(self) -> Result:
        """Extract the Result object"""
        return self.result

    def to_wire(self) -> dict[str, Any]:
        """Convert to wire format (spec-compliant JSON-RPC 2.0)"""
        protocol_data: dict[str, Any] = {}
        protocol_data["result"] = self.result.to_protocol()
        protocol_data["jsonrpc"] = self.jsonrpc
        protocol_data["id"] = self.id
        return protocol_data


class JSONRPCError(ProtocolModel):
    """
    JSON-RPC 2.0 error wrapper for failed MCP requests.

    Wire format for request error responses.
    """

    jsonrpc: str = Field(default=JSONRPC_VERSION, frozen=True)
    id: RequestId
    """
    Identifier matching the original request.
    """

    error: Error
    """
    MCP error payload.
    """

    @classmethod
    def from_error(cls, error: Error, id: RequestId) -> "JSONRPCError":
        """Convert from Error to JSONRPCError"""
        return cls(id=id, error=error)

    def to_error(self) -> Error:
        """Extract the Error object"""
        return self.error

    def to_wire(self) -> dict[str, Any]:
        """Convert to wire format (spec-compliant JSON-RPC 2.0)"""
        protocol_data: dict[str, Any] = {}
        protocol_data["error"] = self.error.to_protocol()
        protocol_data["jsonrpc"] = self.jsonrpc
        protocol_data["id"] = self.id
        return protocol_data
