from typing import Annotated, Literal

from pydantic import Field

from conduit.protocol.base import ProtocolModel, Request, Result
from conduit.protocol.prompts import PromptReference
from conduit.protocol.resources import ResourceReference


class Completion(ProtocolModel):
    """
    Completion response containing multiple available options.
    """

    values: Annotated[list[str], Field(max_length=100)]
    total: int | None = None
    has_more: bool | None = Field(default=None, alias="hasMore")


class CompletionArgument(ProtocolModel):
    """
    Arguments for the completion request.
    """

    name: str
    value: str


class CompleteResult(Result):
    completion: Completion


class CompleteRequest(Request):
    """
    Request from client to server to ask for completion options.
    """

    method: Literal["completion/complete"] = "completion/complete"
    ref: PromptReference | ResourceReference
    argument: CompletionArgument

    @classmethod
    def expected_result_type(cls) -> type[CompleteResult]:
        return CompleteResult
