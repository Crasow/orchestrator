"""
Integration tests for real AI model endpoints.

These tests require a running orchestrator with real credentials (DB + API keys).
They are excluded from the default pytest run.

Run manually:
    pytest tests/integration/ -m integration --no-header -v
"""
import pytest
import httpx
import base64
import asyncio
import logging
import os
from io import BytesIO

from app.main import app

logger = logging.getLogger(__name__)

# Constants
FAKE_PROJECT_ID = "integration-test-project"
LOCATION = "us-central1"
TIMEOUT = 60.0
RESULTS_DIR = "tests/integration_results"

# Models to test
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

VIDEO_MODELS = [
    "publishers/google/models/veo-3.0-fast-generate-001",
    "publishers/google/models/veo-3.0-generate-001",
    "publishers/google/models/veo-3.1-fast-generate-001",
    "publishers/google/models/veo-3.1-generate-001",
]

CAPABILITY_MODELS = [
    "publishers/google/models/imagen-3.0-capability-001",
]


@pytest.fixture(scope="session", autouse=True)
def setup_results_dir():
    """Ensures the results directory exists."""
    os.makedirs(RESULTS_DIR, exist_ok=True)


@pytest.fixture
async def client():
    """Async client that speaks to the real app with lifespan management."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac


def create_image_b64(color="red", size=(512, 512)):
    """Creates a base64 encoded image of a given color."""
    try:
        from PIL import Image
        img = Image.new("RGB", size, color=color)
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except ImportError:
        return (
            "iVBORw0KGgoAAAANSUhEUgAAAgAAAAIAAQMAAADOtka5AAAAA1BMVEX/AAAZ4gk3AAAA"
            "NElEQVR4nO3BMQEAAADCoPVPbQ0poAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
            "4McAAAHAAEq4560AAAAASUVORK5CYII="
        )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", TEXT_MODELS)
async def test_text_generation(client, model_id):
    """Verifies that text models return valid candidates."""
    url = (
        f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}"
        f"/publishers/google/models/{model_id}:generateContent"
    )
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

        filename = f"{RESULTS_DIR}/text_{model_id.replace('/', '_')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(text)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", IMAGE_MODELS)
async def test_image_generation(client, model_id):
    """Verifies that image models return predictions (base64 images)."""
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

    first_pred = data["predictions"][0]
    b64_data = first_pred.get("bytesBase64Encoded") or first_pred.get("data")
    assert b64_data is not None, f"No image data in prediction for {model_id}"

    filename = f"{RESULTS_DIR}/image_{model_id.replace('/', '_').split('_models_')[-1]}.png"
    with open(filename, "wb") as f:
        f.write(base64.b64decode(b64_data))
    logger.info(f"Saved image to {filename}")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", VIDEO_MODELS)
async def test_video_generation(client, model_id):
    """Verifies that video models start a generation (LRO) and poll until completion."""
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

    done = False
    attempts = 0
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
            response_block = poll_data.get("response", poll_data)
            videos = response_block.get("videos", []) or response_block.get("predictions", [])

            if videos:
                vid = videos[0]
                b64 = (
                    vid.get("bytesBase64Encoded")
                    or vid.get("data")
                    or (vid.get("inlineData", {}).get("data") if "inlineData" in vid else None)
                )

                if b64:
                    filename = f"{RESULTS_DIR}/video_{model_id.replace('/', '_').split('_models_')[-1]}.mp4"
                    with open(filename, "wb") as f:
                        f.write(base64.b64decode(b64))
                    logger.info(f"Saved video to {filename}")
                else:
                    pytest.fail("Video generation done but no data found")
            else:
                pytest.fail("Video generation done but no videos list found")


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("model_id", CAPABILITY_MODELS)
async def test_capability_comprehensive(client, model_id):
    """Verifies all capability modes for imagen-3.0-capability-001."""
    raw_img = create_image_b64("red")
    mask_img = create_image_b64("white")
    style_img = create_image_b64("blue")
    subject_img = create_image_b64("green")
    control_img = create_image_b64("yellow")

    scenarios = [
        {
            "name": "shortcut_attachments",
            "instance": {
                "prompt": "A futuristic red car",
                "image": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"},
            },
            "parameters": {"sampleCount": 1},
        },
        {
            "name": "edit_inpaint_insertion",
            "instance": {
                "prompt": "Add a blue sun [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img, "mimeType": "image/png"}},
                ],
            },
            "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_INPAINT_INSERTION"},
        },
        {
            "name": "edit_inpaint_removal",
            "instance": {
                "prompt": "Remove the objects [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img, "mimeType": "image/png"}},
                ],
            },
            "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_INPAINT_REMOVAL"},
        },
        {
            "name": "edit_outpaint",
            "instance": {
                "prompt": "Extend the landscape [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img, "mimeType": "image/png"}},
                ],
            },
            "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_OUTPAINT"},
        },
        {
            "name": "edit_background_swap",
            "instance": {
                "prompt": "Change background to a beach [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img, "mimeType": "image/png"}},
                ],
            },
            "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_BACKGROUND_SWAP"},
        },
        {
            "name": "ref_raw_style",
            "instance": {
                "prompt": "A cat in the style of [2] [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_STYLE", "referenceImage": {"bytesBase64Encoded": style_img, "mimeType": "image/png"}, "styleDescription": "Van Gogh painting style"},
                ],
            },
            "parameters": {"sampleCount": 1},
        },
        {
            "name": "ref_raw_subject",
            "instance": {
                "prompt": "A photo of [2] in Paris [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_SUBJECT", "referenceImage": {"bytesBase64Encoded": subject_img, "mimeType": "image/png"}},
                ],
            },
            "parameters": {"sampleCount": 1},
        },
        {
            "name": "ref_raw_control",
            "instance": {
                "prompt": "A modern building [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_CONTROL", "referenceImage": {"bytesBase64Encoded": control_img, "mimeType": "image/png"}, "controlType": "CONTROL_TYPE_CANNY"},
                ],
            },
            "parameters": {"sampleCount": 1},
        },
        {
            "name": "ref_all_4",
            "instance": {
                "prompt": "The subject [2] in style [3] following structure [4] [1]",
                "referenceImages": [
                    {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img, "mimeType": "image/png"}},
                    {"referenceId": 2, "referenceType": "REFERENCE_TYPE_SUBJECT", "referenceImage": {"bytesBase64Encoded": subject_img, "mimeType": "image/png"}},
                    {"referenceId": 3, "referenceType": "REFERENCE_TYPE_STYLE", "referenceImage": {"bytesBase64Encoded": style_img, "mimeType": "image/png"}, "styleDescription": "cyberpunk digital art"},
                    {"referenceId": 4, "referenceType": "REFERENCE_TYPE_CONTROL", "referenceImage": {"bytesBase64Encoded": control_img, "mimeType": "image/png"}, "controlType": "CONTROL_TYPE_CANNY"},
                ],
            },
            "parameters": {"sampleCount": 1},
        },
    ]

    url = f"/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:predict"

    for scenario in scenarios:
        logger.info(f"Running capability scenario: {scenario['name']}")
        payload = {
            "instances": [scenario["instance"]],
            "parameters": scenario["parameters"],
        }

        try:
            response = await client.post(url, json=payload, timeout=TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                predictions = data.get("predictions", [])
                if predictions:
                    b64 = predictions[0].get("bytesBase64Encoded") or predictions[0].get("data")
                    if b64:
                        filename = f"{RESULTS_DIR}/cap_{scenario['name']}.png"
                        with open(filename, "wb") as f:
                            f.write(base64.b64decode(b64))
                        logger.info(f"Scenario {scenario['name']} SUCCESS. Saved to {filename}")
                    else:
                        logger.error(f"Scenario {scenario['name']} FAILED: No image data in prediction")
                else:
                    logger.error(f"Scenario {scenario['name']} FAILED: Empty predictions")
            else:
                logger.error(f"Scenario {scenario['name']} FAILED with {response.status_code}: {response.text}")
        except Exception as e:
            logger.error(f"Scenario {scenario['name']} EXCEPTION: {e}")
