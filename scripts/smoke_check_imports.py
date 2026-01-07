#!/usr/bin/env python3
#
# Simple import smoke test for core Python dependencies.
# This script is intended to be run in CI or as a local pre-check to ensure
# critical modules can be imported, catching environment or packaging issues early.
#

import sys

def run_smoke_check():
    print("Running Python import smoke checks...")
    modules_to_check = [
        "httpx",
        "fastapi",
        "uvicorn",
        "alpaca_py",
        "firebase_admin",
        "google.cloud.firestore",
        "google.generativeai",
        "dotenv",
        "nats.aio.client", # nats-py
        "pandas",
        "yaml", # PyYAML
    ]

    failed_imports = []
    for module_name in modules_to_check:
        try:
            __import__(module_name)
            print(f"  ✅ Successfully imported: {module_name}")
        except ImportError as e:
            print(f"  ❌ FAILED to import: {module_name} (Error: {e})", file=sys.stderr)
            failed_imports.append(module_name)
        except Exception as e:
            print(f"  ⚠️  Unexpected error importing {module_name}: {e}", file=sys.stderr)
            failed_imports.append(module_name)

    if failed_imports:
        print("\n🔴 Import smoke checks FAILED for the following modules:", file=sys.stderr)
        for module in failed_imports:
            print(f"  - {module}", file=sys.stderr)
        print("\nPlease ensure all required dependencies are installed (e.g., pip install -r requirements.txt)", file=sys.stderr)
        sys.exit(1)
    else:
        print("\n🟢 All Python import smoke checks PASSED.")
        sys.exit(0)

if __name__ == "__main__":
    run_smoke_check()
