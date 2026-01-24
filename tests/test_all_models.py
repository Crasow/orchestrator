import httpx
import asyncio
import logging
from typing import List, Dict, Any

# --- КОНФИГУРАЦИЯ ---
PROXY_URL = "http://localhost:8000"
FAKE_PROJECT_ID = "test-suite-proj"
LOCATION = "us-central1"

# Настройка логов
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("tester")

# Список моделей из твоего providers.yaml
MODELS_TO_TEST = {
    "text": [
        "gemini-2.5-flash",
    ],
    "image": [
        "publishers/google/models/imagen-3.0-fast-generate-001",
        "publishers/google/models/imagen-3.0-generate-002",
        "publishers/google/models/imagen-4.0-fast-generate-001",
        "publishers/google/models/imagen-4.0-generate-001",
        "publishers/google/models/imagen-4.0-ultra-generate-001",
        "publishers/google/models/imagen-3.0-generate-001",
        # "publishers/google/models/imagen-3.0-capability-001", # Пропускаем (нужны референсы)
    ],
    "video": [
        "publishers/google/models/veo-3.0-fast-generate-001",
        "publishers/google/models/veo-3.0-generate-001",
        "publishers/google/models/veo-3.1-fast-generate-001",
        "publishers/google/models/veo-3.1-generate-001",
    ],
}


async def test_text_model(client: httpx.AsyncClient, model_id: str):
    url = f"{PROXY_URL}/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model_id}:generateContent"
    # Для Gemini, если имя модели короткое, путь может быть без publishers/google/models,
    # но API часто прощает это. Если упадет - поправим URL.
    # Vertex API для Gemini обычно: /v1/projects/.../locations/.../publishers/google/models/gemini-pro:generateContent

    # Но для чистоты эксперимента, если ID короткий (без слешей), он подставляется иначе.
    # Твой providers.yaml дает просто "gemini-2.5-flash".
    if "/" not in model_id:
        url = f"{PROXY_URL}/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{model_id}:generateContent"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": "Say 'Test passed' if you hear me."}]}
        ],
        "generationConfig": {"maxOutputTokens": 10},
    }

    try:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200 and "candidates" in resp.json():
            logger.info(f"✅ TEXT  | {model_id:<40} | OK")
        else:
            logger.error(
                f"❌ TEXT  | {model_id:<40} | FAIL ({resp.status_code}) - {resp.text[:100]}"
            )
    except Exception as e:
        logger.error(f"❌ TEXT  | {model_id:<40} | ERROR: {e}")


async def test_image_model(client: httpx.AsyncClient, model_id: str):
    # Убираем префикс publishers/... если он есть в URL, так как мы строим его сами,
    # но в providers.yaml ID уже полные. Прокси их съест.
    # В URL vertex нужно: .../locations/us-central1/publishers/google/models/imagen...
    # Твой ID уже содержит publishers/google/models/... ?
    # В providers.yaml ID выглядят как "publishers/google/models/imagen..."
    # Значит в URL надо подставлять аккуратно.

    # URL construction: .../locations/{LOCATION}/{model_id}:predict
    url = f"{PROXY_URL}/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:predict"

    payload = {
        "instances": [{"prompt": "Blue circle"}],
        "parameters": {"sampleCount": 1},
    }

    try:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            if "predictions" in data and data["predictions"]:
                logger.info(f"✅ IMAGE | {model_id.split('/')[-1]:<40} | OK")
            else:
                logger.error(f"⚠️ IMAGE | {model_id.split('/')[-1]:<40} | EMPTY RESP")
        else:
            logger.error(
                f"❌ IMAGE | {model_id.split('/')[-1]:<40} | FAIL ({resp.status_code})"
            )
    except Exception as e:
        logger.error(f"❌ IMAGE | {model_id.split('/')[-1]:<40} | ERROR: {e}")


async def test_video_model(client: httpx.AsyncClient, model_id: str):
    url = f"{PROXY_URL}/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/{model_id}:predictLongRunning"

    payload = {
        "instances": [{"prompt": "Moving blue circle"}],
        "parameters": {"sampleCount": 1, "durationSeconds": 4},  # Min duration
    }

    try:
        resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            if "name" in data:
                logger.info(
                    f"✅ VIDEO | {model_id.split('/')[-1]:<40} | STARTED (LRO: {data['name'].split('/')[-1]})"
                )
            else:
                logger.error(f"⚠️ VIDEO | {model_id.split('/')[-1]:<40} | NO LRO NAME")
        else:
            logger.error(
                f"❌ VIDEO | {model_id.split('/')[-1]:<40} | FAIL ({resp.status_code})"
            )
    except Exception as e:
        logger.error(f"❌ VIDEO | {model_id.split('/')[-1]:<40} | ERROR: {e}")


async def main():
    logger.info("🚀 STARTING SMOKE TEST FOR ALL GOOGLE MODELS\n")

    async with httpx.AsyncClient(timeout=30) as client:
        # 1. Test Text
        logger.info("--- GEMINI MODELS ---")
        for model in MODELS_TO_TEST["text"]:
            await test_text_model(client, model)

        # 2. Test Image
        logger.info("\n--- IMAGEN MODELS ---")
        for model in MODELS_TO_TEST["image"]:
            await test_image_model(client, model)

        # 3. Test Video
        logger.info("\n--- VEO MODELS ---")
        for model in MODELS_TO_TEST["video"]:
            await test_video_model(client, model)

    logger.info("\n🏁 TEST SUITE FINISHED")


if __name__ == "__main__":
    asyncio.run(main())
