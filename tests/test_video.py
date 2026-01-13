import httpx
import asyncio
import base64
import os
import time

# --- КОНФИГУРАЦИЯ ---
PROXY_URL = "http://localhost:8000"
FAKE_PROJECT_ID = "test-video-project"
MODEL = "publishers/google/models/veo-3.0-generate-001"

# Эндпоинты
BASE_URL = f"{PROXY_URL}/v1/projects/{FAKE_PROJECT_ID}/locations/us-central1/{MODEL}"
URL_START = f"{BASE_URL}:predictLongRunning"
URL_FETCH = f"{BASE_URL}:fetchPredictOperation"

OUTPUT_FOLDER = "test_results_video"


async def test_video_generation():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    # 1. Запуск генерации
    payload_start = {
        "instances": [
            {
                "prompt": "A cinematic drone shot of a futuristic city at sunset, 4k, highly detailed"
            }
        ],
        "parameters": {
            "sampleCount": 1,
            "durationSeconds": 6,
            "aspectRatio": "16:9",
        },
    }

    print(f"[REQ] Запуск генерации видео: {URL_START}")

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp_start = await client.post(URL_START, json=payload_start)
            print(f"[START] Status: {resp_start.status_code}")

            if resp_start.status_code != 200:
                print(f"[FAIL] Не удалось запустить: {resp_start.text}")
                return

            data_start = resp_start.json()
            operation_name = data_start.get("name")
            print(f"[INFO] Операция создана: {operation_name}")

            if not operation_name:
                print("[FAIL] Google не вернул operationName!")
                return

        except Exception as e:
            print(f"[ERR] Ошибка при старте: {e}")
            return

        # 2. Поллинг (ожидание готовности)
        print("\n[POLL] Начинаем ожидание...")
        print(
            "[CHECK] Если Sticky Sessions работают, вы должны видеть только точки (.)."
        )
        print("        Если появляются 'x' или коды ошибок — роутинг сбоит.\n")

        done = False
        attempts = 0

        while (
            not done and attempts < 120
        ):  # Ждем до 10 минут (видео может генериться долго)
            attempts += 1
            await asyncio.sleep(5)

            try:
                payload_fetch = {"operationName": operation_name}
                resp_poll = await client.post(URL_FETCH, json=payload_fetch)

                if resp_poll.status_code == 200:
                    data_poll = resp_poll.json()
                    done = data_poll.get("done", False)

                    if done:
                        print(f"\n[DONE] Генерация завершена! (Попытка {attempts})")
                        process_result(data_poll)
                    else:
                        # 200 OK, но еще не готово — это хороший знак
                        print(".", end="", flush=True)
                else:
                    # Если мы здесь, значит Оркестратор отправил нас не на тот проект
                    print(f"[ERR:{resp_poll.status_code}]", end="", flush=True)

            except Exception as e:
                print(f"![{e}]", end="", flush=True)

    if not done:
        print("\n[TIMEOUT] Видео не сгенерировалось за отведенное время.")


def process_result(data):
    response_block = data.get("response", data)
    videos = response_block.get("videos", [])
    if not videos and "predictions" in response_block:
        videos = response_block["predictions"]

    if not videos:
        print("\n[WARN] Операция завершена, но видео нет в ответе.")
        return

    for i, vid in enumerate(videos):
        b64 = vid.get("bytesBase64Encoded") or vid.get("data")
        if not b64 and "inlineData" in vid:
            b64 = vid["inlineData"].get("data")

        if b64:
            timestamp = int(time.time())
            file_path = f"{OUTPUT_FOLDER}/video_{timestamp}_{i}.mp4"
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(b64))
            print(f"\n[SUCCESS] Видео сохранено: {file_path}")
        else:
            print(f"\n[ERR] Нет данных в видео-объекте {i}")


if __name__ == "__main__":
    asyncio.run(test_video_generation())
