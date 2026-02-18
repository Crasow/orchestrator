import json
import requests
import sys
import os
import time

# Constants
BASE_URL = "http://localhost:8000"
ADMIN_USER = "crasow"
# Default secret from config.py
ADMIN_PASS = "admin12345" 

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_FILE = os.path.join(SCRIPT_DIR, "models.json")
RESULTS_FILE = os.path.join(SCRIPT_DIR, "admin_results.json")

# Status colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def login():
    url = f"{BASE_URL}/admin/login"
    try:
        resp = requests.post(url, json={"username": ADMIN_USER, "password": ADMIN_PASS})
        resp.raise_for_status()
        return resp.json()["access_token"]
    except Exception as e:
        print(f"{RED}Login failed: {e}{RESET}")
        if 'resp' in locals():
            print(f"Response: {resp.text}")
        sys.exit(1)

def load_models():
    try:
        with open(MODELS_FILE, "r") as f:
            return json.load(f)["models"]
    except FileNotFoundError:
        print(f"{RED}Error: {MODELS_FILE} not found.{RESET}")
        sys.exit(1)

def get_providers(token):
    url = f"{BASE_URL}/admin/providers"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"{RED}Failed to get providers: {e}{RESET}")
        sys.exit(1)

def check_provider_key(token, provider_type, identifier, model):
    url = f"{BASE_URL}/admin/test-provider"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "provider": provider_type,
        "identifier": identifier,
        "model": model
    }
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "code": 0, "error": str(e)}

def main():
    print("Logging in...")
    token = login()
    print(f"{GREEN}Logged in.{RESET}")

    print("Fetching providers...")
    providers = get_providers(token)
    
    gemini_keys = providers.get("gemini", [])
    vertex_creds = providers.get("vertex", [])
    
    print(f"Found {len(gemini_keys)} Gemini keys and {len(vertex_creds)} Vertex projects.")

    print("Loading models...")
    models = load_models()
    print(f"Loaded {len(models)} models.")
    
    full_results = {
        "gemini": {},
        "vertex": {}
    }

    # Process Gemini
    if gemini_keys:
        print("\n" + "="*80)
        print("TESTING GEMINI KEYS")
        print("="*80)
        
        for k_info in gemini_keys:
            idx = k_info["index"]
            mask = k_info["mask"]
            print(f"\nKey: {mask}")
            
            key_results = []
            
            for model in models:
                # Filter models that are not generateContent compatible for basic check if desired, 
                # but server handles it.
                model_name = model["name"]
                clean_name = model_name.split("/")[-1]
                
                print(f"  Checking {clean_name:<40}", end="\r")
                
                res = check_provider_key(token, "gemini", idx, model)
                
                status = res.get("status")
                code = res.get("code")
                error_msg = res.get("error")
                
                entry = {
                    "model": model_name,
                    "status": code,
                    "result": status,
                    "error": error_msg
                }
                key_results.append(entry)
                
                if status == "working":
                     print(f"  [{GREEN}OK{RESET}] {clean_name:<40} ({code})")
                elif status == "skipped":
                     print(f"  [{YELLOW}SKIP{RESET}] {clean_name:<40}")
                else:
                     err_display = error_msg if error_msg else "Unknown Error"
                     # Truncate long error
                     if isinstance(err_display, dict):
                         err_display = json.dumps(err_display)
                     if len(str(err_display)) > 100:
                         err_display = str(err_display)[:100] + "..."
                         
                     print(f"  [{RED}FAIL{RESET}] {clean_name:<40} ({code}) - {err_display}")

            full_results["gemini"][mask] = key_results

    # Process Vertex
    if vertex_creds:
        print("\n" + "="*80)
        print("TESTING VERTEX CREDENTIALS")
        print("="*80)
        
        for c_info in vertex_creds:
            pid = c_info["project_id"]
            print(f"\nProject: {pid}")
            
            cred_results = []
            
            for model in models:
                model_name = model["name"]
                clean_name = model_name.split("/")[-1]
                
                print(f"  Checking {clean_name:<40}", end="\r")
                
                res = check_provider_key(token, "vertex", pid, model)
                
                status = res.get("status")
                code = res.get("code")
                error_msg = res.get("error")
                
                entry = {
                    "model": model_name,
                    "status": code,
                    "result": status,
                    "error": error_msg
                }
                cred_results.append(entry)
                
                if status == "working":
                     print(f"  [{GREEN}OK{RESET}] {clean_name:<40} ({code})")
                elif status == "skipped":
                     print(f"  [{YELLOW}SKIP{RESET}] {clean_name:<40}")
                else:
                     err_display = error_msg if error_msg else "Unknown Error"
                     if isinstance(err_display, dict):
                         err_display = json.dumps(err_display)
                     if len(str(err_display)) > 100:
                         err_display = str(err_display)[:100] + "..."
                     print(f"  [{RED}FAIL{RESET}] {clean_name:<40} ({code}) - {err_display}")

            full_results["vertex"][pid] = cred_results

    # Save Results
    with open(RESULTS_FILE, "w") as f:
        json.dump(full_results, f, indent=2)
    print(f"\nDetailed results saved to {RESULTS_FILE}")

if __name__ == "__main__":
    main()
