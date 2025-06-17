from typing import Annotated, Literal

from pydantic import AnyUrl, UrlConstraints, field_validator

from conduit.protocol.base import Notification, ProtocolModel, Request, Result


class Root(ProtocolModel):
    """
    A root of the client.
    """

    uri: Annotated[
        AnyUrl, UrlConstraints(host_required=False)
    ]  # TODO: Allow strings explicitly
    """
    URI must start with file:// in this version of the protocol.
    """
    name: str | None = None

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, v: AnyUrl) -> AnyUrl:
        if not str(v).startswith("file://"):
            raise ValueError(
                "Root URI must start with file:// "
                "(current protocol version requirement)"
            )
        return v


class ListRootsRequest(Request):
    """
    Request to list the roots of the client.
    """

    method: Literal["roots/list"] = "roots/list"


class ListRootsResult(Result):
    """
    Response containing the roots of the client.
    """

    roots: list[Root]


class RootsListChangedNotification(Notification):
    """
    Notification that the roots of the client have changed.
    """

    method: Literal["notifications/roots/list_changed"] = (
        "notifications/roots/list_changed"
    )
