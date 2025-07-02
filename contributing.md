# Contributing

Contributions are welcome! We're building a delightful Python SDK for the Model Context Protocol.

## Prerequisites

- Python 3.12+
- uv (recommended for environment management)

## Setup

Clone the repository:

```bash
git clone https://github.com/davenpi/conduit-mcp.git 
cd conduit-mcp
```

Create and sync the environment:

```bash
uv sync
```

This installs all dependencies, including dev tools.

Activate the virtual environment (e.g., `source .venv/bin/activate` or via your IDE).

## Code quality

We use pre-commit for formatting, linting, and type-checking. All PRs must pass these checks.

Install the hooks locally:

```bash
pre-commit install
# or with uv
uv run pre-commit install
```

The hooks run automatically on `git commit`. You can also run them manually:

```bash
pre-commit run --all-files
# or with uv
uv run pre-commit run --all-files
```

# Set up commit message template
git config commit.template .gitmessage