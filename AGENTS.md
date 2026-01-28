# AGENTS.md - Codebase Conventions for Agentic Coding

This document outlines the conventions and practices for agentic coding agents operating within this repository. Adhering to these guidelines ensures consistency, maintainability, and quality across the codebase.

## 1. Build, Lint, and Test Commands

### 1.1 Build/Setup

To set up the development environment and install dependencies, use `pip` with `pyproject.toml`:

```bash
pip install .
# Or for editable installation (for development)
pip install -e .
```

### 1.2 Linting

No explicit linting configuration was found. For maintaining code quality, agents should adhere to PEP 8.
It is recommended to use a linter like `ruff` or `flake8` to check for style violations.

**Example Linting Command (using ruff, if installed):**
```bash
ruff check .
```

**Example Formatting Command (using black, if installed):**
```bash
black .
```

### 1.3 Testing

This project uses `pytest` for testing.

**Run all tests:**
```bash
pytest
```

**Run a single test file:**
```bash
pytest tests/unit/test_security.py
```

**Run a specific test function within a file:**
```bash
pytest tests/unit/test_security.py::TestSecurity::test_something
```

**Run tests by marker:**
The `pytest.ini` defines several markers: `slow`, `integration`, `unit`, `security`, `vertex`, `gemini`, `imagen`, `veo`.

*   **Run only unit tests:**
    ```bash
    pytest -m unit
    ```
*   **Run only integration tests:**
    ```bash
    pytest -m integration
    ```
*   **Run security tests:**
    ```bash
    pytest -m security
    ```
*   **Run tests for Gemini models:**
    ```bash
    pytest -m gemini
    ```
*   **Exclude slow tests:**
    ```bash
    pytest -m "not slow"
    ```

**Additional Pytest Options:**
From `pytest.ini`, the default options include coverage reporting:
`-ra --strict-markers --strict-config --cov=app --cov-report=term-missing --cov-report=html --cov-report=xml`

## 2. Code Style Guidelines

### 2.1 Imports

*   **Order**: Imports should generally be grouped in the following order:
    1.  Standard library imports (e.g., `os`, `sys`, `typing`).
    2.  Third-party library imports (e.g., `fastapi`, `httpx`).
    3.  Local application/project-specific imports.
*   **Alphabetical**: Within each group, imports should be sorted alphabetically.
*   **Absolute Imports**: Prefer absolute imports over relative imports where possible.
    *   **Good**: `from app.core import logging`
    *   **Bad**: `from .core import logging` (if `core` is not a direct sibling of the current module)

### 2.2 Formatting

*   Adhere to **PEP 8** style guide.
*   **Indentation**: Use 4 spaces for indentation.
*   **Line Length**: Aim for a maximum of 79 characters per line, as per PEP 8.
*   **Blank Lines**: Use two blank lines between top-level function or class definitions, and one blank line between method definitions.

### 2.3 Types

*   Use **type hints** (`typing` module) for function arguments, return values, and variables to improve readability and maintainability.
    *   **Example**: `def process_data(data: dict) -> list[str]:`

### 2.4 Naming Conventions

*   Follow **PEP 8** naming conventions:
    *   **Modules**: `lowercase_with_underscores.py`
    *   **Packages**: `lowercase_with_underscores`
    *   **Classes**: `CamelCase`
    *   **Functions/Methods**: `lowercase_with_underscores`
    *   **Variables**: `lowercase_with_underscores`
    *   **Constants**: `ALL_CAPS_WITH_UNDERSCORES`

### 2.5 Error Handling

*   Use specific exception types rather than broad `except Exception:` clauses.
*   Log errors with appropriate logging levels (e.g., `logging.error`, `logging.warning`).
*   Handle expected errors gracefully and provide informative error messages.

### 2.6 Comments and Docstrings

*   **Comments**: Use comments sparingly, primarily to explain *why* certain code exists or complex logic, rather than *what* it does. Code should be self-documenting where possible.
*   **Docstrings**: Use PEP 257 compliant docstrings for all modules, classes, and public functions/methods.
    *   **Module Docstrings**: Briefly describe the module's purpose.
    *   **Class Docstrings**: Describe the class's purpose and its main attributes.
    *   **Function/Method Docstrings**: Describe the function's purpose, arguments, and what it returns.

### 2.7 FastAPI Specific Guidelines

Given the use of FastAPI:
*   **Pydantic Models**: Use Pydantic models for request and response body validation and serialization.
*   **Dependency Injection**: Leverage FastAPI's dependency injection system for managing dependencies.

## 3. Cursor/Copilot Rules

No specific Cursor or Copilot instruction files (`.cursor/rules/` or `.github/copilot-instructions.md`) were found in this repository. Agents should follow the general code style guidelines outlined above.
