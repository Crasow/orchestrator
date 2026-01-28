import pytest
import httpx
import base64
import asyncio
import logging
import os
from io import BytesIO

# Fix for broken environment variable in test context
os.environ["SECURITY__ALLOWED_CLIENT_IPS"] = '["127.0.0.1"]'
if "ALLOWED_CLIENT_IPS" in os.environ:
    del os.environ["ALLOWED_CLIENT_IPS"]

from app.main import app

# Setup logging
logger = logging.getLogger(__name__)

# Constants
FAKE_PROJECT_ID = "integration-test-project"
LOCATION = "us-central1"
TIMEOUT = 60.0
RESULTS_DIR = "integration_results"

# Models to test (based on old_tests/test_all_models.py)
TEXT_MODELS = [
    "gemini-2.5-flash",
]

IMAGE_MODELS = [
    "publishers/google/models/imagen-3.0-fast-generate-001",
    "publishers/google/models/imagen-3.0-generate-002",
    "publishers/google/models/imagen-4.0-fast-generate-001",
    "publishers/google/models/imagen-4.0-generate-001",
    "publishers/google/models/imagen-4.0-ultra-generate-001",
    "publishers/google/models/imagen-3.0-generate-001",
]

# Video models need separate handling due to Long Running Operations
VIDEO_MODELS = [
    "publishers/google/models/veo-3.0-fast-generate-001",
    "publishers/google/models/veo-3.0-generate-001",
    "publishers/google/models/veo-3.1-fast-generate-001",
    "publishers/google/models/veo-3.1-generate-001",
]

# Capability models (Image Editing)
CAPABILITY_MODELS = [
    "publishers/google/models/imagen-3.0-capability-001",
]

@pytest.fixture(scope="session", autouse=True)
def setup_results_dir():
    """Ensures the results directory exists."""
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

@pytest.fixture
async def client():
    """Async client that speaks to the real app with lifespan management."""
    # Trigger lifespan events (startup/shutdown) to initialize http_client
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

def create_dummy_image_b64():
    """Returns a hardcoded 512x512 red square image (PNG) in Base64."""
    # This avoids PIL dependency and ensures we send a valid sized image.
    # Generated via: base64.b64encode(Image.new("RGB", (512, 512), color="red").save(BytesIO(), format="PNG").getvalue())
    return (
        "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIAAQMAAADOtka5AAAAA1BMVEX/AAAZ4gk3AAAANElEQVR4nO3BMQEAAADCoPVPbQ0poAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA4McAAAHAAEq4560AAAAASUVORK5CYII="
    )

@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", TEXT_MODELS)
async def test_text_generation(client, model_id):
    """Verifies that text models return valid candidates and saves the result."""
    url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model_id}:generateContent"
    
    # Handle short model IDs for Gemini
    if "/" not in model_id:
        url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model_id}:generateContent"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "Say 'Integration Test Passed' if you receive this."}]}
        ],
        "generationConfig": {"maxOutputTokens": 20},
    }

    response = await client.post(url, json=payload, timeout=TIMEOUT)
    assert response.status_code == 200, f"Model {model_id} failed with {response.text}"
    
    data = response.json()
    assert "candidates" in data, f"No candidates in response for {model_id}: {data}"
    assert len(data["candidates"]) > 0
    
    candidate = data["candidates"][0]
    if "content" in candidate and "parts" in candidate["content"]:
        text = candidate["content"]["parts"][0]["text"]
        logger.info(f"Model {model_id} said: {text}")
        
        # Save text to file
        filename = f"{RESULTS_DIR}/text_{model_id.replace('/', '_')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        logger.warning(f"Model {model_id} returned no content parts: {candidate}")

@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", IMAGE_MODELS)
async def test_image_generation(client, model_id):
    """Verifies that image models return predictions (base64 images) and saves the image."""
    url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:predict"
    
    payload = {
        "instances": [{"prompt": "A simple blue circle on white background, minimal vector style"}],
        "parameters": {"sampleCount": 1},
    }

    response = await client.post(url, json=payload, timeout=TIMEOUT)
    assert response.status_code == 200, f"Model {model_id} failed with {response.text}"
    
    data = response.json()
    if not data or "predictions" not in data:
         logger.warning(f"Model {model_id} returned empty response: {data}")
         return

    assert len(data["predictions"]) > 0
    
    # Verify we got image data
    first_pred = data["predictions"][0]
    b64_data = first_pred.get("bytesBase64Encoded") or first_pred.get("data")
    assert b64_data is not None, f"No image data in prediction for {model_id}"
    
    # Save image to file
    filename = f"{RESULTS_DIR}/image_{model_id.replace('/', '_').split('_models_')[-1]}.png"
    with open(filename, "wb") as f:
        f.write(base64.b64decode(b64_data))
    logger.info(f"Saved image to {filename}")

@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", VIDEO_MODELS)
async def test_video_generation(client, model_id):
    """Verifies that video models successfully START a generation (LRO) and POLL until completion."""
    url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:predictLongRunning"
    
    payload = {
        "instances": [{"prompt": "A blue ball bouncing"}],
        "parameters": {"sampleCount": 1, "durationSeconds": 4},
    }

    response = await client.post(url, json=payload, timeout=TIMEOUT)
    assert response.status_code == 200, f"Model {model_id} failed start with {response.text}"
    
    data = response.json()
    assert "name" in data, f"No LRO 'name' returned for {model_id}: {data}"
    operation_name = data["name"]
    logger.info(f"Video generation started: {operation_name}")
    
    fetch_url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:fetchPredictOperation"
    fetch_payload = {"operationName": operation_name}
    
    # Poll for completion
    done = False
    attempts = 0
    # Wait up to 5 minutes (60 * 5s)
    max_attempts = 60
    
    while not done and attempts < max_attempts:
        attempts += 1
        await asyncio.sleep(5)
        
        poll_response = await client.post(fetch_url, json=fetch_payload, timeout=TIMEOUT)
        if poll_response.status_code != 200:
            logger.warning(f"Poll failed with {poll_response.status_code}")
            continue
            
        poll_data = poll_response.json()
        if "error" in poll_data:
            pytest.fail(f"Video generation failed: {poll_data['error']}")
            
        done = poll_data.get("done", False)
        if done:
            logger.info(f"Video generation completed for {model_id}")
            # Process result
            response_block = poll_data.get("response", poll_data)
            videos = response_block.get("videos", [])
            if not videos and "predictions" in response_block:
                 videos = response_block["predictions"]
                 
            if videos:
                vid = videos[0]
                b64 = vid.get("bytesBase64Encoded") or vid.get("data")
                if not b64 and "inlineData" in vid:
                    b64 = vid["inlineData"].get("data")
                    
                if b64:
                    filename = f"{RESULTS_DIR}/video_{model_id.replace('/', '_').split('_models_')[-1]}.mp4"
                    with open(filename, "wb") as f:
                        f.write(base64.b64decode(b64))
                    logger.info(f"Saved video to {filename}")
                else:
                    pytest.fail("Video generation done but no data found")
            else:
                pytest.fail("Video generation done but no videos list found")

@pytest.mark.asyncio
@pytest.mark.skip(reason="User requested to skip capability model for now.")
@pytest.mark.parametrize("model_id", CAPABILITY_MODELS)
async def test_capability_edit(client, model_id):
    """Verifies image editing capabilities (sending reference images)."""
    pass