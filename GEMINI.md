# GEMINI.md

## Project Overview

This project is a Python-based AI services orchestrator, built using the FastAPI framework. Its primary purpose is to act as a secure and reliable proxy for Google AI services, specifically Vertex AI and Gemini.

The orchestrator handles:
- **Authentication:** Provides token-based admin authentication for administrative tasks.
- **Credential Rotation:** Automatically rotates API keys for Gemini and service account credentials for Vertex AI to enhance security and availability.
- **Request Proxying:** Routes incoming requests to the appropriate Google AI service based on the request path.
- **Dynamic Project ID Substitution:** For Vertex AI requests, it dynamically replaces the project ID in the request path with the project ID from the currently active service account.
- **Configuration:** Uses a structured configuration system based on `pydantic-settings`, allowing for easy configuration via environment variables or a `.env` file.
- **Security:** Supports encrypted storage of Gemini API keys and IP-based access control.

## Building and Running

### Prerequisites
- Python 3.13+
- `pip`

### Setup
1. **Install dependencies:**
   ```bash
   pip install .
   ```
   For development, install in editable mode:
   ```bash
   pip install -e .
   ```

### Running the Application
The application can be run using `uvicorn`:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Development Conventions

### Code Style
- The project follows the PEP 8 style guide for Python code.
- It uses `ruff` for linting and formatting, as indicated by the presence of a `.ruff_cache` directory.

### Configuration
- Application configuration is managed through environment variables and a `.env` file.
- The `app/config.py` file defines the configuration schema using `pydantic-settings`.

### Security
- The application uses JWT for admin authentication.
- It supports encrypting Gemini API keys using the `cryptography` library.
- Access to the proxy can be restricted to a whitelist of IP addresses.

### Dependencies
- **FastAPI:** The core web framework.
- **uvicorn:** The ASGI server used to run the application.
- **httpx:** Used for making asynchronous HTTP requests to the Google AI services.
- **google-auth:** Used for authenticating with Google Cloud services.
- **pydantic-settings:** Used for managing application configuration.
- **cryptography:** Used for encrypting and decrypting Gemini API keys.
- **PyJWT:** Used for generating and verifying JWTs.
