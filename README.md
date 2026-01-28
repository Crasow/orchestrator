# AI Services Orchestrator

## Project Description
A secure proxy for Google AI services, including Vertex AI and Gemini. This orchestrator handles authentication, credential rotation, and request proxying to ensure reliable and secure access to various AI models.

## Features
*   **Secure Proxy**: Routes requests to Google AI services (Vertex AI, Gemini).
*   **Credential Rotation**: Manages and rotates API keys and service account credentials for high availability and security.
*   **Authentication**: Admin login with token-based authentication.
*   **Admin Endpoints**:
    *   `/admin/login`: Authenticate and receive an access token.
    *   `/admin/reload`: Hot-reload API keys/credentials without service interruption.
    *   `/admin/status`: View current system status, including credential counts and suspicious activity.
*   **Rate Limiting**: Simple rate limiting implementation (can be extended).
*   **Error Handling and Retries**: Automatically retries requests on certain provider errors (e.g., 429, 403, 503).
*   **Project ID Substitution**: Dynamically replaces project IDs for Vertex AI requests.

## Installation

### Prerequisites
*   Python 3.13+
*   `pip`

### Setup
1.  Clone the repository:
    ```bash
    git clone https://github.com/your-repo/orchestrator.git
    cd orchestrator
    ```
2.  Install dependencies:
    ```bash
    pip install .
    # For development, install in editable mode:
    pip install -e .
    ```

## Configuration
Environment variables are used for configuration. Key variables include:
*   `ENABLE_DOCS`: Set to `true` to enable FastAPI documentation (`/docs`).
*   `GEMINI_BASE_URL`: Base URL for Gemini API (e.g., `https://generativelanguage.googleapis.com`).
*   `VERTEX_BASE_URL`: Base URL for Vertex AI API (e.g., `https://us-central1-aiplatform.googleapis.com`).
*   `MAX_RETRIES`: Maximum number of retries for proxy requests.
*   `ADMIN_USERNAME`: Username for admin login.
*   `ADMIN_PASSWORD`: Password for admin login.
*   `JWT_SECRET_KEY`: Secret key for JWT token generation.
*   `VERTEX_CREDENTIALS_PATH`: Path to a directory containing Vertex AI service account JSON files.
*   `GEMINI_API_KEYS_PATH`: Path to a file containing Gemini API keys, one per line.

## Usage

### Running the application
The application can be run using `uvicorn`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
For production, remove `--reload` and consider using a process manager like Gunicorn.

### Admin Endpoints
Access the admin endpoints for management.
*   **Login**: `POST /admin/login` with `{"username": "your_admin_username", "password": "your_admin_password"}` in the request body to get a JWT token.
*   **Reload Credentials**: `POST /admin/reload` with a valid JWT in the `Authorization: Bearer <token>` header.
*   **System Status**: `GET /admin/status` with a valid JWT in the `Authorization: Bearer <token>` header.

### Proxying AI Requests
Requests to AI services are proxied through the orchestrator. For example:
*   **Gemini**: `POST /v1beta/models/gemini-pro:generateContent` will be forwarded to the configured `GEMINI_BASE_URL`.
*   **Vertex AI**: `POST /v1/projects/<project_id>/locations/<location>/publishers/google/models/<model_id>:predict` will have `<project_id>` replaced with the rotated Vertex AI project ID.

## Testing
The project uses `pytest` for testing.

### Run all tests
```bash
pytest
```

### Run specific tests
*   **Single test file**:
    ```bash
    pytest tests/unit/test_security.py
    ```
*   **Specific test function**:
    ```bash
    pytest tests/unit/test_security.py::TestSecurity::test_something
    ```

### Run tests by marker
*   **Unit tests**: `pytest -m unit`
*   **Integration tests**: `pytest -m integration`
*   **Security tests**: `pytest -m security`
*   **Gemini-specific tests**: `pytest -m gemini`
*   **Exclude slow tests**: `pytest -m "not slow"`

## Code Style and Contributions
Please refer to `AGENTS.md` for detailed code style guidelines, import orders, naming conventions, error handling, and other contribution guidelines.

## License
[Consider adding a license here, e.g., MIT, Apache 2.0]
