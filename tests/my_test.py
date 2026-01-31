import json
import requests
import sys
import os
import base64

# 1. Настройки
FAKE_PROJECT_ID = "test-project-id"
LOCATION = "us-central1"
MODEL_ID = "imagen-3.0-capability-001"
ORCHESTRATOR_URL = "http://localhost:8000"

# URL прокси
url = f"{ORCHESTRATOR_URL}/v1beta1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{MODEL_ID}:predict"

# 2. Хелпер для загрузки реальных картинок
def load_real_image(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(path):
        with open(path, "rb") as f:
            print(f"Загружен файл: {filename}")
            return base64.b64encode(f.read()).decode("utf-8")
    else:
        print(f"ВНИМАНИЕ: Файл {filename} не найден! Сценарии с ним могут упасть.")
        return None

# Загружаем реальные ассеты
raw_img_b64 = load_real_image("photo1.jpg")
mask_img_b64 = load_real_image("mask1.png")     # Обычно PNG для масок
style_img_b64 = load_real_image("style1.jpg")
subject_img_b64 = load_real_image("subject1.jpg")
control_img_b64 = load_real_image("control1.jpg")

# 3. Сценарии (используют только загруженные данные)
scenarios = []

if raw_img_b64:
    scenarios.append({
        "name": "1. Shortcut Attachments (Simple)",
        "payload": {
            "instances": [
                {
                    "prompt": "Make it look like a sketch [1]",
                    "referenceImages": [
                        {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}}
                    ]
                }
            ],
            "parameters": {"sampleCount": 1, "aspectRatio": "1:1"}
        }
    })

if raw_img_b64 and mask_img_b64:
    scenarios.extend([
        {
            "name": "2. Edit: Inpaint Insertion (RAW + MASK)",
            "payload": {
                "instances": [
                    {
                        "prompt": "Add a futuristic object [1]",
                        "referenceImages": [
                            {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                            {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img_b64, "mimeType": "image/png"}}
                        ]
                    }
                ],
                "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_INPAINT_INSERTION"}
            }
        },
        {
            "name": "3. Edit: Inpaint Removal (RAW + MASK)",
            "payload": {
                "instances": [
                    {
                        "prompt": "Remove the objects [1]",
                        "referenceImages": [
                            {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                            {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img_b64, "mimeType": "image/png"}}
                        ]
                    }
                ],
                "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_INPAINT_REMOVAL"}
            }
        },
        {
            "name": "4. Edit: Outpaint (RAW + MASK)",
            "payload": {
                "instances": [
                    {
                        "prompt": "Extend the landscape [1]",
                        "referenceImages": [
                            {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                            {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img_b64, "mimeType": "image/png"}}
                        ]
                    }
                ],
                "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_OUTPAINT"}
            }
        },
        {
            "name": "5. Edit: Background Swap (RAW + MASK)",
            "payload": {
                "instances": [
                    {
                        "prompt": "Change background to a snowy mountain [1]",
                        "referenceImages": [
                            {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                            {"referenceId": 2, "referenceType": "REFERENCE_TYPE_MASK", "referenceImage": {"bytesBase64Encoded": mask_img_b64, "mimeType": "image/png"}}
                        ]
                    }
                ],
                "parameters": {"sampleCount": 1, "editMode": "EDIT_MODE_BACKGROUND_SWAP"}
            }
        }
    ])

if raw_img_b64 and style_img_b64:
    scenarios.append({
        "name": "6. Style Transfer (RAW + STYLE)",
        "payload": {
            "instances": [
                {
                    "prompt": "The scene in the style of [2] [1]",
                    "referenceImages": [
                        {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                        {"referenceId": 2, "referenceType": "REFERENCE_TYPE_STYLE", "referenceImage": {"bytesBase64Encoded": style_img_b64, "mimeType": "image/jpeg"}, 
                         "styleDescription": "high-quality artistic style"}
                    ]
                }
            ],
            "parameters": {"sampleCount": 1}
        }
    })

if raw_img_b64 and subject_img_b64:
    scenarios.append({
        "name": "7. Subject Reference (RAW + SUBJECT)",
        "payload": {
            "instances": [
                {
                    "prompt": "Put the subject [2] into the context [1]",
                    "referenceImages": [
                        {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                        {"referenceId": 2, "referenceType": "REFERENCE_TYPE_SUBJECT", "referenceImage": {"bytesBase64Encoded": subject_img_b64, "mimeType": "image/jpeg"}}
                    ]
                }
            ],
            "parameters": {"sampleCount": 1}
        }
    })

if raw_img_b64 and control_img_b64:
    scenarios.append({
        "name": "8. Control Reference (RAW + CONTROL)",
        "payload": {
            "instances": [
                {
                    "prompt": "Build this scene [1]",
                    "referenceImages": [
                        {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                        {"referenceId": 2, "referenceType": "REFERENCE_TYPE_CONTROL", "referenceImage": {"bytesBase64Encoded": control_img_b64, "mimeType": "image/jpeg"},
                         "controlType": "CONTROL_TYPE_CANNY"}
                    ]
                }
            ],
            "parameters": {"sampleCount": 1}
        }
    })

if raw_img_b64 and subject_img_b64 and style_img_b64 and control_img_b64:
    scenarios.append({
        "name": "9. ALL COMBO (RAW + SUBJECT + STYLE + CONTROL)",
        "payload": {
            "instances": [
                {
                    "prompt": "The subject [2] in style [3] with structure [4] in the scene [1]",
                    "referenceImages": [
                        {"referenceId": 1, "referenceType": "REFERENCE_TYPE_RAW", "referenceImage": {"bytesBase64Encoded": raw_img_b64, "mimeType": "image/jpeg"}},
                        {"referenceId": 2, "referenceType": "REFERENCE_TYPE_SUBJECT", "referenceImage": {"bytesBase64Encoded": subject_img_b64, "mimeType": "image/jpeg"}},
                        {"referenceId": 3, "referenceType": "REFERENCE_TYPE_STYLE", "referenceImage": {"bytesBase64Encoded": style_img_b64, "mimeType": "image/jpeg"}, "styleDescription": "vibrant digital art"},
                        {"referenceId": 4, "referenceType": "REFERENCE_TYPE_CONTROL", "referenceImage": {"bytesBase64Encoded": control_img_b64, "mimeType": "image/jpeg"}, "controlType": "CONTROL_TYPE_CANNY"}
                    ]
                }
            ],
            "parameters": {"sampleCount": 1}
        }
    })

# Заголовки
headers = {"Content-Type": "application/json; charset=utf-8"}

print(f"=== ЗАПУСК ТЕСТОВ SCENARIOS ({len(scenarios)} шт) ===")
print(f"URL: {url}")

for i, scenario in enumerate(scenarios):
    print(f"\n--- Scenario {i+1}: {scenario['name']} ---")
    
    try:
        response = requests.post(url, headers=headers, json=scenario["payload"])
        
        if response.status_code == 200:
            data = response.json()
            predictions = data.get("predictions", [])
            if predictions:
                print(f"✅ УСПЕХ! Получено изображений: {len(predictions)}")
                # Сохраняем результат
                img_data = predictions[0].get("bytesBase64Encoded")
                fname = f"output_scenario_{scenario['name'].split('.')[0].strip()}.png"
                with open(fname, "wb") as f:
                    f.write(base64.b64decode(img_data))
                print(f"   Сохранено в {fname}")
            else:
                print("⚠️  Ответ 200, но нет predictions:", data)
        else:
            print(f"❌ ОШИБКА {response.status_code}:")
            try:
                err_json = response.json()
                print(json.dumps(err_json, indent=2))
            except:
                print(response.text)
                
    except requests.exceptions.ConnectionError:
        print("❌ CRITICAL: Не удалось подключиться к оркестратору.")
        break
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")

print("\n=== ТЕСТЫ ЗАВЕРШЕНЫ ===")