import json
import os
import requests
import time

# Paths / constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_FILE = os.path.join(SCRIPT_DIR, "models.json")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "results.json")
FAKE_PROJECT_ID = "test-project-id"
LOCATION = "us-central1"
# BASE_URL = f"http://localhost:8000/v1/projects/{FAKE_PROJECT_ID}/locations/{LOCATION}/publishers/google/models"
BASE_URL = f"http://localhost:8000/v1beta/models"

# Status colors for terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def load_models():
    try:
        with open(MODELS_FILE, "r") as f:
            return json.load(f)["models"]
    except FileNotFoundError:
        print(f"{RED}Error: {MODELS_FILE} not found.{RESET}")
        return []

def check_model(model, model_type):
    model_name = model["name"]
    # Handle model names that might already have "models/" prefix or not
    clean_name = model_name.split("/")[-1] 
    
    url = ""
    payload = {}

    if model_type == "text":
        url = f"{BASE_URL}/{clean_name}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "Hi"}]}],
            "generationConfig": {"maxOutputTokens": 10}
        }
    elif model_type == "image":
        url = f"{BASE_URL}/{clean_name}:predict"
        # Minimal payload for Imagen
        payload = {
            "instances": [{"prompt": "A small blue circle"}],
            "parameters": {"sampleCount": 1}
        }
    elif model_type == "video":
        url = f"{BASE_URL}/{clean_name}:predictLongRunning"
        # Minimal payload for Veo (this might start a job, so we just want to see if it accepts the request)
        # We might not want to actually start a video gen for a simple check, but to get 200 we might have to.
        # Alternatively, we can check if it returns 400 (Bad Request) instead of 404 (Not Found).
        payload = {
            "instances": [{"prompt": "A cat jumping"}],
            "parameters": {}
        }

    try:
        print(f"Checking {model_name}...", end="\r")
        response = requests.post(url, json=payload, timeout=30)
        
        error_text = None
        if response.status_code != 200:
            try:
                # Try to get structured JSON error if possible
                error_text = response.json()
            except:
                error_text = response.text

        if response.status_code == 200:
            return "working", response.status_code, None
        elif response.status_code == 404:
            return "not_found", response.status_code, error_text
        else:
            return "error", response.status_code, error_text
    except requests.exceptions.RequestException as e:
        return "connection_error", 0, str(e)

def main():
    models = load_models()
    if not models:
        return

    results = {"working": [], "failed": []}

    print(f"Starting check for {len(models)} models...\n")

    for model in models:
        methods = model.get("supportedGenerationMethods", [])
        
        # Determine type
        if "generateContent" in methods:
            m_type = "text"
        elif "predict" in methods:
            m_type = "image"
        elif "predictLongRunning" in methods:
            m_type = "video"
        else:
            m_type = "unknown"

        if m_type == "unknown":
            continue

        status, code, error_msg = check_model(model, m_type)
        
        result_entry = {
            "name": model["name"],
            "type": m_type,
            "status": status,
            "code": code,
            "error": error_msg
        }

        if status == "working":
            results["working"].append(result_entry)
            print(f"[{GREEN}OK{RESET}] {model['name']:<50} ({code})")
        else:
            results["failed"].append(result_entry)
            # Differentiate connection error vs status code
            code_display = code if isinstance(code, int) else "ERR"
            print(f"[{RED}FAIL{RESET}] {model['name']:<50} ({code_display})")

    print("\n" + "="*60)
    print(f"SUMMARY")
    print("="*60)
    print(f"Total Working: {len(results['working'])}")
    print(f"Total Failed:  {len(results['failed'])}")
    print("="*60)

    if results["working"]:
        print(f"\n{GREEN}Available Models:{RESET}")
        for m in results["working"]:
            print(f" - {m['name']} ({m['type']})")

    if results["failed"]:
        print(f"\n{RED}Unavailable Models:{RESET}")
        for m in results["failed"]:
            print(f" - {m['name']} ({m['type']}) : Status {m['code']}")

    # Save to file
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
