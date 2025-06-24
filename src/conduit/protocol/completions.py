"""
Autocomplete support for MCP prompt and resource arguments.

MCP enables servers to offer reusable, parameterized prompts - think "code review"
templates that take language, focus area, and code as arguments. When users fill
out these templates, they need smart autocomplete for argument values.

## The Completion Flow

1. **Discovery**: Client discovers available prompts and their argument schemas
2. **User Input**: User selects a prompt and starts filling argument values
3. **Completion**: As they type, client requests suggestions for the current argument
4. **Suggestions**: Server responds with relevant completions based on partial input

For example, a "weather" prompt with a `city` argument might suggest
"San Francisco", "San Diego", "San Antonio" when the user types "San".

## Why This Matters

Without completion, users would need to guess valid argument values or consult
documentation. With completion, prompt templates become as easy to use as
IDE autocomplete - turning complex, reusable prompts into guided experiences.

The completion system works for both prompts and resources, making MCP servers
feel responsive and user-friendly rather than opaque APIs.
"""

from typing import Annotated, Literal

from pydantic import Field

from conduit.protocol.base import ProtocolModel, Request, Result
from conduit.protocol.prompts import PromptReference
from conduit.protocol.resources import ResourceTemplateReference


class Completion(ProtocolModel):
    """
    Autocomplete suggestions for a prompt or resource argument.

    Contains the actual completion values plus metadata about whether more
    options are available. The server can send up to 100 suggestions while
    indicating if additional matches exist.
    """

    values: Annotated[list[str], Field(max_length=100)]
    """
    Up to 100 completion suggestions matching the user's input.
    """

    total: int | None = None
    """
    Total number of possible completions, if known.
    """

    has_more: bool | None = Field(default=None, alias="hasMore")
    """
    Whether additional completions exist beyond those returned.
    """


class CompletionArgument(ProtocolModel):
    """
    The argument being completed by the user.

    Identifies which parameter they're filling out and what they've typed
    so far, enabling the server to provide relevant suggestions.
    """

    name: str
    """
    Name of the argument being completed.
    """

    value: str
    """
    Current partial value the user has entered.
    """


class CompletionContext(ProtocolModel):
    """Additional context for completion requests."""

    arguments: dict[str, str] | None = None
    """
    Previously-resolved variables in a URI template or prompt.
    
    Provides context about other argument values that have already been
    set, which can help generate more relevant completion suggestions.
    """


class CompleteRequest(Request):
    """
    Request autocomplete suggestions for a prompt or resource argument.

    Sent when a user is typing an argument value and needs completion options.
    For example, completing a "city" argument with "San" might return suggestions
    like "San Francisco", "San Diego", etc.
    """

    method: Literal["completion/complete"] = "completion/complete"
    ref: PromptReference | ResourceTemplateReference
    """
    The prompt or resource containing the argument being completed.
    """

    argument: CompletionArgument
    """
    Details about which argument is being completed and its current value.
    """

    context: CompletionContext | None = None
    """
    Additional context for completion requests.
    """

    @classmethod
    def expected_result_type(cls) -> type["CompleteResult"]:
        return CompleteResult


class CompleteResult(Result):
    """
    Server's response containing autocomplete suggestions.

    Provides completion options that match the user's partial input,
    along with metadata about whether more suggestions are available.
    """

    completion: Completion
