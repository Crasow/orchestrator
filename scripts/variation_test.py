import httpx
import asyncio
import base64
import os
import logging
from io import BytesIO

# --- НАСТРОЙКИ ---
# IP твоего сервера (или localhost, если тестишь локально)
PROXY_URL = "http://localhost:8000" 
FAKE_PROJECT = "test-proj"
MODEL = "publishers/google/models/imagen-3.0-capability-001"
ENDPOINT = f"/v1/projects/{FAKE_PROJECT}/locations/us-central1/{MODEL}:predict"

# Промпт из твоего примера
PROMPT = "Сделай вариацию изображения, сохрани композицию, добавь кинематографичный свет [1]"

# --- ЛОГГЕР ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("TEST")

def create_test_image():
    """Генерирует тестовую картинку (красный квадрат), если нет файла."""
    try:
        from PIL import Image
        img = Image.new('RGB', (512, 512), color='red')
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except ImportError:
        logger.warning("PIL не установлен. Шлем микро-картинку.")
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

async def test_variation():
    url = f"{PROXY_URL}{ENDPOINT}"
    image_b64 = base64.b64encode(open("tests/photo_2026-01-31_18-08-41.jpg", "rb").read()).decode('utf-8')
    
    logger.info(f"Отправляем запрос на: {url}")
    logger.info(f"Промпт: {PROMPT}")

    # Формируем правильный Payload для Google Capability
    payload = {
        "instances": [
            {
                "prompt": PROMPT,
                "referenceImages": [
                    {
                        "referenceType": "REFERENCE_TYPE_RAW",
                        "referenceId": 1,
                        "referenceImage": {
                            "bytesBase64Encoded": image_b64,
                            "mimeType": "image/png"
                        }
                    }
                ]
            }
        ],
        "parameters": {
            "sampleCount": 1,
            # Режим редактирования/вариации
            "editMode": "EDIT_MODE_INPAINT_INSERTION", 
            # Можно добавить aspect ratio, если нужно
            # "aspectRatio": "1:1" 
        }
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(url, json=payload)
            
            if resp.status_code == 200:
                logger.info("✅ Успех! Ответ получен.")
                data = resp.json()
                # Сохраняем результат
                predictions = data.get("predictions", [])
                for i, pred in enumerate(predictions):
                    b64 = pred.get("bytesBase64Encoded")
                    if b64:
                        with open(f"variation_result_{i}.png", "wb") as f:
                            f.write(base64.b64decode(b64))
                        logger.info(f"Картинка сохранена: variation_result_{i}.png")
            else:
                logger.error(f"❌ Ошибка {resp.status_code}: {resp.text}")

        except Exception as e:
            logger.error(f"Ошибка соединения: {e}")

if __name__ == "__main__":
    asyncio.run(test_variation())