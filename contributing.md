# Contributing to conduit-mcp

Welcome! We're building an SDK that's powerful and intuitive. These practices help us deliver on that promise together.

## Quick Start

**Prerequisites:**
- Python 3.12+
- uv (recommended for environment management)

**Setup:**
```bash
git clone https://github.com/Lab11HQ/conduit-mcp.git
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

2. **Make your changes:**
   ```python
   # In src/conduit/shared/utils.py
   def filter_truthy_values(data: dict[str, Any]) -> dict[str, Any]:
      """Remove keys with falsy values from a dictionary."""
      return {k: v for k, v in data.items() if v}
   ```

3. **Write tests:**
   ```python
   # In tests/shared/test_utils.py
   class TestUtils:
      def test_filter_truthy_values(self):
         # Arrange
         messy_data = {"name": "Alice", "age": 0, "email": "", "active": True}
         
         # Act
         clean_data = filter_truthy_values(messy_data)
         
         # Assert
         assert clean_data == {"name": "Alice", "active": True}
   ```

4. **Push and create a PR:**
   ```bash
   git push -u origin feat/your-feature-name
   ```

### Commit Messages

The `.gitmessage` template guides you toward structured commits:

```text
feat: add filter_truthy_values utility function

What changed and why:

Added filter_truthy_values() to shared/utils.py to clean dictionaries
by removing keys with falsy values. Useful for sanitizing API responses
and config data.

Impact:

Provides a reusable utility for common data cleaning tasks across the
codebase. Follows our typing and testing standards with comprehensive
test coverage.
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

**Note**
I turned off Pyright since it won't recognize Pydantic aliases properly (grr). I run
`npx pyright path/to/code` periodically to make sure the type checker is happy.

## Testing

```bash
# Run the full test suite
pytest

# Run specific tests
pytest tests/client/session/
```

## Questions?

Open an issue or start a discussion. We're here to help you contribute successfully!