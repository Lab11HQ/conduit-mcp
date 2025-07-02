# Contributing to conduit-mcp

Welcome! We're building an SDK that's powerful and intuitive. These practices help us deliver on that promise together.

## Quick Start

**Prerequisites:**
- Python 3.12+
- uv (recommended for environment management)

**Setup:**
```bash
git clone https://github.com/davenpi/conduit-mcp.git 
cd conduit-mcp
uv sync
```

**Install development tools:**
```bash
# Set up commit message template
git config commit.template .gitmessage

# Install pre-commit hooks
uv run pre-commit install
```

You're ready to contribute!

## Development Workflow

### Working on Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feat/your-feature-name
   # or fix/bug-description, docs/improvement, etc.
   ```

2. **Make your changes**

3. **Push and create a PR:**
   ```bash
   git push -u origin feat/your-feature-name
   ```

### Commit Messages

The `.gitmessage` template guides you toward structured commits:

```text
feat: add defensive parsing to response handling

What changed and why:

Enhanced _parse_response() to handle malformed server responses gracefully instead
of letting validation errors pass silently.

Impact:

Makes the SDK robust against misbehaving servers while maintaining the typed
request/response contract.
```

**Why structured commits?**
- Easier debugging and code archaeology
- Keeps commits focused
- Faster onboarding for new contributors (human and AI!)

## Code Quality

We use automated tools to maintain consistency:

```bash
# Run all checks (formatting, linting)
uv run pre-commit run --all-files

# Or let them run automatically on commit
git commit  # hooks run automatically
```

**Our standards:**
- Type hints for all public APIs
- Clear, narrative docs
- Comprehensive tests for documented behavior

## Testing

```bash
# Run the full test suite
uv run pytest

# Run specific tests
uv run pytest tests/client/session/
```

We aim for comprehensive test coverage, especially for the public API surface.

## Questions?

Open an issue or start a discussion. We're here to help you contribute successfully!