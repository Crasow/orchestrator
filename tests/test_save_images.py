import httpx
import asyncio
import base64
import os
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
PROXY_URL = "http://localhost:8000"
# ID проекта может быть любым, прокси его заменит на реальный
FAKE_PROJECT_ID = "test-project-id"
# Модель для теста (Imagen 3)
MODEL = "publishers/google/models/imagen-3.0-generate-001"
ENDPOINT = f"/v1/projects/{FAKE_PROJECT_ID}/locations/us-central1/{MODEL}:predict"
OUTPUT_FOLDER = "test_results"


async def test_generation_and_save():
    # 1. Создаем папку для картинок
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
        print(f"[INIT] Создана папка: {OUTPUT_FOLDER}")

    url = f"{PROXY_URL}{ENDPOINT}"

    # 2. Формируем запрос
    payload = {
        "instances": [
            {
                "prompt": "A futuristic cyberpunk city with neon lights, cinematic lighting, highly detailed, 8k"
            }
        ],
        "parameters": {"sampleCount": 1, "aspectRatio": "16:9"},
    }

    print(f"[REQ] Отправка запроса на: {url}")

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            # Отправляем POST запрос без авторизации (ее добавит прокси)
            response = await client.post(url, json=payload)

            print(f"[RESP] Статус код: {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                # Vertex AI возвращает список в ключе "predictions"
                # См. логику _parse_image_generate_result в google_client.py
                predictions = data.get("predictions", [])

                if not predictions:
                    print("[WARN] Ответ пришел успешный, но массив 'predictions' пуст.")
                    print("Raw output:", data)
                    return

                for index, pred in enumerate(predictions):
                    # Достаем данные
                    b64_data = pred.get("bytesBase64Encoded")
                    mime_type = pred.get("mimeType", "image/png")

                    # Определяем расширение
                    ext = "png"
                    if "jpeg" in mime_type or "jpg" in mime_type:
                        ext = "jpg"

                    if b64_data:
                        # Декодируем Base64 в байты
                        image_bytes = base64.b64decode(b64_data)

                        # Генерируем уникальное имя файла
                        timestamp = datetime.now().strftime("%H-%M-%S")
                        filename = f"{OUTPUT_FOLDER}/img_{timestamp}_{index}.{ext}"

                        # Сохраняем на диск
                        with open(filename, "wb") as f:
                            f.write(image_bytes)

                        print(f"[SUCCESS] Картинка сохранена: {filename}")
                    else:
                        print(
                            f"[ERR] В предсказании {index} нет данных bytesBase64Encoded"
                        )
            else:
                print(f"[FAIL] Ошибка сервера: {response.text}")

        except httpx.RequestError as e:
            print(f"[ERR] Ошибка соединения: {e}")
        except Exception as e:
            print(f"[ERR] Непредвиденная ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(test_generation_and_save())
