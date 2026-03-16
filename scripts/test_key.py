#!/usr/bin/env python3
"""
Interactive script to test a specific credential (Gemini API key or Vertex JSON)
with different model types: text (Gemini), image (Imagen), video (Veo).

Usage:
  Interactive:  python scripts/test_key.py
  With args:    python scripts/test_key.py <key_number> <model_name> [type]

  type: text (default), image, video

Examples:
  python scripts/test_key.py 1 gemini-2.5-flash
  python scripts/test_key.py 1 gemini-2.5-flash text
  python scripts/test_key.py 3 imagen-3.0-generate-001 image
  python scripts/test_key.py 2 veo-3.0-fast-generate-001 video
"""

import os
import sys
import json
import glob
import base64
import asyncio
from datetime import datetime

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEMINI_KEYS_FILE = os.path.join(PROJECT_ROOT, "credentials", "gemini", "api_keys.json")
VERTEX_CREDS_DIR = os.path.join(PROJECT_ROOT, "credentials", "vertex")

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
VERTEX_BASE_URL = "https://us-central1-aiplatform.googleapis.com"

# ---------------------------------------------------------------------------
# Default request bodies per type
# ---------------------------------------------------------------------------
TEXT_BODY = {
    "contents": [
        {"role": "user", "parts": [{"text": "Say hello in one sentence."}]}
    ],
}

IMAGE_BODY = {
    "instances": [
        {"prompt": "A cute cat astronaut floating in space, digital art"}
    ],
    "parameters": {
        "sampleCount": 1,
        "aspectRatio": "1:1",
    },
}

VIDEO_BODY = {
    "instances": [
        {"prompt": "A golden retriever running on a beach in slow motion"}
    ],
    "parameters": {},
}

# type -> (action suffix, request body)
TYPE_CONFIG = {
    "text":  ("generateContent",      TEXT_BODY),
    "image": ("predict",              IMAGE_BODY),
    "video": ("predictLongRunning",   VIDEO_BODY),
}


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------
def load_all_credentials() -> list[dict]:
    creds = []

    if os.path.exists(GEMINI_KEYS_FILE):
        with open(GEMINI_KEYS_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            for key in data:
                if isinstance(key, str) and key.strip():
                    creds.append({
                        "type": "gemini",
                        "label": f"Gemini key ...{key[-6:]}",
                        "api_key": key,
                    })

    if os.path.isdir(VERTEX_CREDS_DIR):
        files = sorted(glob.glob(os.path.join(VERTEX_CREDS_DIR, "*.json")))
        for fpath in files:
            try:
                with open(fpath, "r") as f:
                    info = json.load(f)
                if "private_key" not in info or "project_id" not in info:
                    continue
                creds.append({
                    "type": "vertex",
                    "label": f"Vertex project {info['project_id']} ({os.path.basename(fpath)})",
                    "project_id": info["project_id"],
                    "json_path": fpath,
                })
            except Exception as e:
                print(f"  [!] Failed to load {fpath}: {e}")

    return creds


def print_credentials(creds: list[dict]) -> None:
    print("\nAvailable credentials:")
    print("-" * 60)
    for i, c in enumerate(creds, 1):
        print(f"  {i}) [{c['type'].upper():6s}] {c['label']}")
    print("-" * 60)


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------
def select_credential(creds: list[dict], choice: int | None = None) -> dict:
    if choice is not None:
        idx = choice - 1
        if idx < 0 or idx >= len(creds):
            print(f"Error: number {choice} out of range (1-{len(creds)})")
            sys.exit(1)
        return creds[idx]

    while True:
        raw = input(f"\nSelect credential number [1-{len(creds)}]: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(creds):
            return creds[int(raw) - 1]
        print("Invalid input, try again.")


def get_model_name(model: str | None = None) -> str:
    if model:
        return model
    name = input("Enter model name (e.g. gemini-2.5-flash): ").strip()
    if not name:
        print("Error: model name cannot be empty")
        sys.exit(1)
    return name


def get_test_type(test_type: str | None = None) -> str:
    valid = ("text", "image", "video")
    if test_type:
        if test_type not in valid:
            print(f"Error: type must be one of {valid}, got '{test_type}'")
            sys.exit(1)
        return test_type

    print("\nTest types:")
    print("  1) text   -Gemini generateContent")
    print("  2) image  -Imagen predict")
    print("  3) video  -Veo predictLongRunning")

    while True:
        raw = input("Select test type [1-3 or text/image/video]: ").strip().lower()
        if raw in ("1", "text"):
            return "text"
        if raw in ("2", "image"):
            return "image"
        if raw in ("3", "video"):
            return "video"
        print("Invalid input, try again.")


# ---------------------------------------------------------------------------
# Send requests
# ---------------------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPTS_DIR, "test_output")


def _save_media(resp_json: dict, model: str, test_type: str) -> None:
    """Save generated text/image/video from response to test_output/ folder."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if test_type == "text":
        # Extract text from generateContent response
        parts = []
        for candidate in resp_json.get("candidates", []):
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    parts.append(part["text"])
        if parts:
            text = "\n".join(parts)
            filename = f"{model}_{timestamp}.txt"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"  [OK] Saved: {filepath}")
        return

    if test_type == "image":
        predictions = resp_json.get("predictions", [])
        for i, pred in enumerate(predictions):
            b64 = pred.get("bytesBase64Encoded")
            mime = pred.get("mimeType", "image/png")
            if not b64:
                continue
            ext = mime.split("/")[-1].replace("jpeg", "jpg")
            filename = f"imagen_{timestamp}_{i}.{ext}"
            filepath = os.path.join(OUTPUT_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"  [OK] Saved: {filepath}")

    elif test_type == "video":
        predictions = resp_json.get("predictions", resp_json.get("videos", []))
        if isinstance(predictions, list):
            for i, pred in enumerate(predictions):
                b64 = pred.get("bytesBase64Encoded")
                mime = pred.get("mimeType", "video/mp4")
                if not b64:
                    continue
                ext = mime.split("/")[-1]
                filename = f"veo_{timestamp}_{i}.{ext}"
                filepath = os.path.join(OUTPUT_DIR, filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(b64))
                print(f"  [OK] Saved: {filepath}")


def _print_response(resp: httpx.Response, model: str, test_type: str) -> None:
    print(f"<- Status: {resp.status_code}")
    try:
        body = resp.json()

        # Save output if successful
        if resp.status_code == 200:
            _save_media(body, model, test_type)

        # Print JSON but truncate base64 blobs for readability
        text = json.dumps(body, indent=2, ensure_ascii=False)
        if len(text) > 5000:
            text = text[:5000] + "\n... (truncated)"
        print(text)
    except Exception:
        print(resp.text[:5000])


async def test_gemini(
    api_key: str, model: str, action: str, request_body: dict,
    test_type: str,
) -> None:
    url = f"{GEMINI_BASE_URL}/v1/models/{model}:{action}"
    params = {"key": api_key}
    print(f"\n-> POST {url}")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=request_body, params=params)

    _print_response(resp, model, test_type)


async def _poll_operation(
    client: httpx.AsyncClient, op_name: str, headers: dict,
    model: str, test_type: str,
    interval: int = 10, max_attempts: int = 60,
) -> None:
    """Poll a Vertex long-running operation until done, then save the result."""
    # Extract project/location/operation from the full operation name
    # e.g. "projects/X/locations/Y/publishers/google/models/Z/operations/ID"
    parts = op_name.split("/")
    project = parts[1]
    location = parts[3]
    op_id = parts[-1]
    poll_url = (
        f"{VERTEX_BASE_URL}/v1/projects/{project}"
        f"/locations/{location}/operations/{op_id}"
    )
    print(f"\n[...] Polling operation (every {interval}s, up to {max_attempts} attempts)...")

    for attempt in range(1, max_attempts + 1):
        await asyncio.sleep(interval)
        resp = await client.get(poll_url, headers=headers)

        if resp.status_code != 200:
            print(f"  [{attempt}/{max_attempts}] HTTP {resp.status_code}: {resp.text[:200]}")
            continue

        try:
            body = resp.json()
        except Exception:
            print(f"  [{attempt}/{max_attempts}] Invalid JSON: {resp.text[:200]}")
            continue

        done = body.get("done", False)
        print(f"  [{attempt}/{max_attempts}] done={done}")

        if done:
            response = body.get("response", body)
            _save_media(response, model, test_type)

            text = json.dumps(body, indent=2, ensure_ascii=False)
            if len(text) > 5000:
                text = text[:5000] + "\n... (truncated)"
            print(text)
            return

    print("  [FAIL] Timed out waiting for operation to complete.")


async def test_vertex(
    json_path: str, project_id: str, model: str,
    action: str, request_body: dict, test_type: str,
) -> None:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    creds = service_account.Credentials.from_service_account_file(
        json_path, scopes=scopes
    )
    creds.refresh(Request())
    token = creds.token

    url = (
        f"{VERTEX_BASE_URL}/v1/projects/{project_id}"
        f"/locations/us-central1/publishers/google/models/{model}:{action}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": project_id,
    }
    print(f"\n-> POST {url}")

    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(url, json=request_body, headers=headers)

        # If long-running operation, poll until done
        if resp.status_code == 200:
            body = resp.json()
            op_name = body.get("name")
            if op_name and not body.get("done", False) and "predictions" not in body:
                print(f"<- Status: {resp.status_code}")
                print(f"  Operation: {op_name}")
                await _poll_operation(client, op_name, headers, model, test_type)
                return

        _print_response(resp, model, test_type)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main():
    creds = load_all_credentials()
    if not creds:
        print("No credentials found!")
        sys.exit(1)

    # Parse CLI args: <key_number> <model> [type]
    arg_num = None
    arg_model = None
    arg_type = None

    if len(sys.argv) >= 2:
        arg_num = int(sys.argv[1])
    if len(sys.argv) >= 3:
        arg_model = sys.argv[2]
    if len(sys.argv) >= 4:
        arg_type = sys.argv[3]

    print_credentials(creds)

    selected = select_credential(creds, arg_num)
    model = get_model_name(arg_model)
    test_type = get_test_type(arg_type)

    action, request_body = TYPE_CONFIG[test_type]

    print(f"\nUsing:   {selected['label']}")
    print(f"Model:   {model}")
    print(f"Type:    {test_type}")
    print(f"Action:  {action}")

    if selected["type"] == "gemini":
        await test_gemini(selected["api_key"], model, action, request_body, test_type)
    else:
        await test_vertex(
            selected["json_path"], selected["project_id"],
            model, action, request_body, test_type,
        )


if __name__ == "__main__":
    asyncio.run(main())
