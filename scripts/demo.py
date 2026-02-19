import asyncio
import base64
import json
import logging
import os
import sys
import httpx

# --- НАСТРОЙКИ ---
BASE_URL = "http://localhost:8000"
OUTPUT_DIR = "demo_results"
FAKE_PROJECT = "demo-project"
LOCATION = "us-central1"
TIMEOUT = 120.0  # Увеличим тайм-аут для генерации

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("demo")

# --- МОДЕЛИ ---
TEXT_MODELS = [
    "gemini-2.0-flash",
    "gemini-1.5-pro",
]

IMAGE_MODELS = [
    "publishers/google/models/imagen-3.0-generate-001",
    "publishers/google/models/imagen-3.0-fast-generate-001",
]

VIDEO_MODELS = [
    "publishers/google/models/veo-3.0-fast-generate-001", 
]

async def ensure_output_dir():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        logger.info(f"Created output directory: {OUTPUT_DIR}")

async def run_text_generation(client: httpx.AsyncClient, model: str):
    logger.info(f"--- Testing Text: {model} ---")
    url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/publishers/google/models/{model}:generateContent"
    
    # Убираем publishers/google/models если модель указана коротко (для Gemini)
    if "/" not in model:
        url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/publishers/google/models/{model}:generateContent"
    else:
        # Если модель указана полностью, но URL требует правки (для Vertex endpoint'ов)
        # Для Gemini обычно endpoint выглядит так:
        pass 

    # Для Gemini 1.5/2.0 путь часто такой:
    if "gemini" in model:
         url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/publishers/google/models/{model}:generateContent"

    payload = {
        "contents": [{"role": "user", "parts": [{"text": "Write a haiku about artificial intelligence."}]}],
        "generationConfig": {"maxOutputTokens": 100},
    }

    try:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        if "candidates" in data and data["candidates"]:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            logger.info(f"Result: {text.strip()}")
            
            filename = os.path.join(OUTPUT_DIR, f"text_{model.replace('/', '_')}.txt")
            with open(filename, "w", encoding="utf-8") as f:
                f.write(text)
            logger.info(f"Saved to {filename}")
        else:
            logger.warning(f"No candidates returned: {data}")

    except Exception as e:
        logger.error(f"Failed to generate text with {model}: {e}")

async def run_image_generation(client: httpx.AsyncClient, model: str):
    logger.info(f"--- Testing Image: {model} ---")
    # Endpoint для Imagen (Vertex AI)
    # Формат: /v1/projects/{project}/locations/{location}/publishers/google/models/{model}:predict
    # Но в переменной model уже есть 'publishers/google/models/...'
    
    # Корректируем URL. Если model содержит полный путь, используем его часть
    if "publishers" in model:
        # model = "publishers/google/models/imagen-..."
        url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/{model}:predict"
    else:
        url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/publishers/google/models/{model}:predict"

    payload = {
        "instances": [{"prompt": "A futuristic city with flying cars, cyberpunk style, high detail"}],
        "parameters": {"sampleCount": 1, "aspectRatio": "16:9"},
    }

    try:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Error {response.status_code}: {response.text}")
            return

        data = response.json()
        predictions = data.get("predictions", [])
        
        if predictions:
            # Imagen может возвращать bytesBase64Encoded
            b64_data = predictions[0].get("bytesBase64Encoded")
            
            if b64_data:
                filename = os.path.join(OUTPUT_DIR, f"image_{model.split('/')[-1]}.png")
                with open(filename, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                logger.info(f"Saved to {filename}")
            else:
                logger.warning(f"No base64 data in prediction: {predictions[0].keys()}")
        else:
            logger.warning(f"No predictions returned: {data}")

    except Exception as e:
        logger.error(f"Failed to generate image with {model}: {e}")

async def run_video_generation(client: httpx.AsyncClient, model: str):
    logger.info(f"--- Testing Video: {model} ---")
    
    if "publishers" in model:
        url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/{model}:predictLongRunning"
    else:
        url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/publishers/google/models/{model}:predictLongRunning"

    payload = {
        "instances": [{"prompt": "A cute robot dancing in the rain, cinematic lighting"}],
        "parameters": {"sampleCount": 1, "durationSeconds": 4}, # Veo 3.0 поддерживает 4 сек?
    }

    try:
        # 1. Start Operation
        logger.info("Starting video generation (this takes time)...")
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Failed to start video: {response.text}")
            return

        data = response.json()
        operation_name = data.get("name")
        if not operation_name:
            logger.error(f"No operation name returned: {data}")
            return

        logger.info(f"Operation started: {operation_name}")

        # 2. Poll Operation
        fetch_url = f"/v1/projects/{FAKE_PROJECT}/locations/{LOCATION}/{model}:fetchPredictOperation"
        fetch_payload = {"operationName": operation_name}
        
        attempts = 0
        while attempts < 60: # 5 минут макс
            await asyncio.sleep(5)
            attempts += 1
            
            poll_resp = await client.post(fetch_url, json=fetch_payload)
            if poll_resp.status_code != 200:
                logger.warning(f"Poll error: {poll_resp.status_code}")
                continue

            poll_data = poll_resp.json()
            
            if "error" in poll_data:
                logger.error(f"Generation failed: {poll_data['error']}")
                return
            
            if poll_data.get("done"):
                logger.info("Generation complete!")
                # Extract video
                response_block = poll_data.get("response", poll_data) # Иногда response вложен, иногда нет
                
                # В Veo 3.0 результат часто в 'videos' или 'predictions' внутри response
                videos = response_block.get("videos", []) or response_block.get("predictions", [])
                
                if videos:
                    vid = videos[0]
                    # Данные могут быть в bytesBase64Encoded или data
                    b64 = vid.get("bytesBase64Encoded") or vid.get("data")
                    # Иногда video uri, но мы ждем base64
                    
                    if b64:
                        filename = os.path.join(OUTPUT_DIR, f"video_{model.split('/')[-1]}.mp4")
                        with open(filename, "wb") as f:
                            f.write(base64.b64decode(b64))
                        logger.info(f"Saved video to {filename}")
                    else:
                        logger.warning(f"No video data found in result: {vid.keys()}")
                else:
                    logger.warning(f"No videos list in response: {response_block.keys()}")
                
                return

        logger.error("Timeout waiting for video generation")

    except Exception as e:
        logger.error(f"Failed to generate video with {model}: {e}")

async def main():
    await ensure_output_dir()
    
    logger.info(f"Connecting to Orchestrator at {BASE_URL}...")
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # Проверка здоровья (опционально, через админку или просто запрос)
        # ...
        
        # 1. Text
        for model in TEXT_MODELS:
            await run_text_generation(client, model)
            
        # 2. Images
        for model in IMAGE_MODELS:
            await run_image_generation(client, model)
            
        # 3. Videos
        for model in VIDEO_MODELS:
            await run_video_generation(client, model)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.critical(f"Unexpected error: {e}")
