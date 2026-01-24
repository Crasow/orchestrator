import httpx
import asyncio
import base64
import os
import logging
from io import BytesIO

# --- ЛОГИРОВАНИЕ ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] CAP-TEST: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_capability")

# --- КОНФИГУРАЦИЯ ---
PROXY_URL = "http://localhost:8000"
FAKE_PROJECT_ID = "test-cap-project"
MODEL = "publishers/google/models/imagen-3.0-capability-001"
ENDPOINT = f"/v1/projects/{FAKE_PROJECT_ID}/locations/us-central1/{MODEL}:predict"
OUTPUT_FOLDER = "test_results_capability"


def create_dummy_image_b64():
    """Создает красный квадрат 512x512 и возвращает Base64."""
    try:
        from PIL import Image

        img = Image.new("RGB", (512, 512), color="red")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")
    except ImportError:
        logger.warning("PIL не установлен. Используется встроенный микро-квадрат.")
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


async def test_capability_edit():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    url = f"{PROXY_URL}{ENDPOINT}"
    image_b64 = create_dummy_image_b64()
    logger.info("Подготовлена тестовая картинка (Base64)")

    # 5. Правильный Payload для Imagen 3 Capability (Edit/Instruct)
    # Используем referenceImages с типом RAW.
    payload = {
        "instances": [
            {
                # Указываем [1], чтобы сослаться на referenceId=1
                "prompt": "Turn the red color into blue [1]",
                "referenceImages": [
                    {
                        "referenceType": "REFERENCE_TYPE_RAW",
                        "referenceId": 1,
                        "referenceImage": {
                            "bytesBase64Encoded": image_b64,
                            "mimeType": "image/png",
                        },
                    }
                ],
            }
        ],
        "parameters": {
            "sampleCount": 1,
            # editMode обязателен для редактирования.
            # INPAINT_INSERTION - универсальный режим для изменений по промпту
            "editMode": "EDIT_MODE_INPAINT_INSERTION",
            # Можно добавить maskMode: "MASK_MODE_BACKGROUND" для авто-маски, если нужно
        },
    }

    logger.info(f"Отправка запроса на: {url}")

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(url, json=payload)
            logger.info(f"Статус код: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"Ошибка Google: {response.text}")
                return

            data = response.json()
            predictions = data.get("predictions", [])

            if not predictions:
                logger.warning("Пустой ответ (нет predictions).")
                return

            for i, pred in enumerate(predictions):
                b64 = pred.get("bytesBase64Encoded") or pred.get("data")
                if b64:
                    out_path = f"{OUTPUT_FOLDER}/result_{i}.png"
                    with open(out_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                    logger.info(f"✅ Успех! Результат сохранен: {out_path}")
                else:
                    logger.error("Нет данных в ответе")

        except Exception as e:
            logger.error(f"Ошибка теста: {e}")


if __name__ == "__main__":
    asyncio.run(test_capability_edit())
