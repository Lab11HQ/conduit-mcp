"""
Filesystem scope discovery for MCP servers.

Roots define what filesystem locations a server can access and operate on.
Servers use this information to understand their operating environment,
validate file operations, and tailor their offered capabilities to the
available scope.

## Discovery Flow

1. **Server asks** - "What filesystem locations can I access?" via ListRootsRequest
2. **Client responds** - Provides list of allowed directories and files
3. **Server adapts** - Configures capabilities based on available access
4. **Dynamic updates** - Client notifies server when access boundaries change

## Practical Usage

A code analysis server might discover it has access to `/home/user/projects`
and then offer tools for analyzing project structure, finding configuration
files, or searching codebases—all scoped to the available directories.

Roots help servers operate effectively within their allowed boundaries while
giving clients control over what filesystem locations are accessible.
"""

from typing import Any, Literal

from pydantic import Field

from conduit.protocol.base import Notification, ProtocolModel, Request, Result


class Root(ProtocolModel):
    """
    A filesystem resource that the server can access.

    Roots define the boundaries of what a server can work with—think of them as
    declaring "here are the directories and files you're allowed to touch."
    This creates a secure sandbox while enabling servers to apply their domain
    expertise to your local content.

    Instead of manually feeding files into conversations, you can point servers
    at project directories and let them intelligently traverse, analyze, and
    work with the file structure as their capabilities require.
    """

    uri: str
    """
    The location this server can access.

    Supports file:// URIs for local filesystem access and other URI schemes
    depending on server capabilities.
    """

    name: str | None = None
    """
    Optional human-readable identifier for this root.
    
    Useful for display purposes or referencing specific roots when
    working with multiple locations.
    """

    metadata: dict[str, Any] | None = Field(default=None, alias="_meta")
    """
    Additional metadata about the root.
    """


class ListRootsRequest(Request):
    """
    Server request to discover what filesystem locations it can access.

    Servers send this to understand their operating boundaries—what directories
    and files the client has made available. This shapes how the server can
    apply its capabilities to the client's content.
    """

    method: Literal["roots/list"] = "roots/list"

    @classmethod
    def expected_result_type(cls) -> type["ListRootsResult"]:
        return ListRootsResult


class ListRootsResult(Result):
    """
    Client response defining the server's allowed operating scope.

    Each root represents a location the server can read from and potentially
    modify, establishing the boundaries for filesystem-based operations.
    """

    roots: list[Root]


class RootsListChangedNotification(Notification):
    """
    Client notification that filesystem access boundaries have changed.

    Sent when roots are added, removed, or modified—perhaps when users
    open new projects or revoke access to directories. Servers typically
    respond by requesting the updated root list to understand their new
    operating scope.
    """

    method: Literal["notifications/roots/list_changed"] = (
        "notifications/roots/list_changed"
    )
