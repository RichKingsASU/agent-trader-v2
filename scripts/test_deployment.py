import subprocess
import time
import sys
import os
import signal

# --- Configuration ---
IMAGE_NAME = "agenttrader-local-test"
CONTAINER_NAME = "agenttrader-test-runner"
# Local port mapping (Container 8080 -> Local 8080)
PORT = "8080"


def out(msg: str = "") -> None:
    sys.stdout.write(str(msg) + "\n")


def run_command(cmd, shell=False):
    """Executes a shell command and streams output."""
    out(f"🔹 Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        if shell:
            subprocess.check_call(cmd, shell=True)
        else:
            subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        out(f"❌ Error executing command. Exit code: {e.returncode}")
        sys.exit(1)

def cleanup_container():
    """Forces removal of the test container if it exists."""
    out(f"\n🧹 Cleaning up old container '{CONTAINER_NAME}'...")
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

def build_image():
    """Builds the Docker image using the production Dockerfile."""
    out("🔨 Building Docker image...")
    # We use the actual Dockerfile to ensure we test exactly what we deploy
    run_command(["docker", "build", "-t", IMAGE_NAME, "."])

def run_container():
    """Runs the container with simulated Cloud Run environment variables."""
    out(f"🚀 Starting container '{CONTAINER_NAME}'...")
    
    # Load secrets from your local environment or define dummies for smoke testing
    # NOTE: Ensure these vars are set in your terminal before running this script, 
    # or replace 'os.getenv' with actual test keys if safe.
    env_vars = [
        "-e", f"DATABASE_URL={os.getenv('DATABASE_URL', 'postgresql://user:pass@localhost:5432/db')}",
        "-e", f"APCA_API_KEY_ID={os.getenv('APCA_API_KEY_ID', 'test_key')}",
        "-e", f"APCA_API_SECRET_KEY={os.getenv('APCA_API_SECRET_KEY', 'test_secret')}",
        "-e", f"APCA_API_BASE_URL={os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')}",
        "-e", "ALPACA_DATA_FEED=sip",
        "-e", "LOG_LEVEL=DEBUG",
        "-e", "PORT=8080",
        # Important: Simulate the "Gen2" environment
        "-e", "K_SERVICE=market-streamer",
        "-e", "K_REVISION=local-v1"
    ]

    # The command overrides the CMD to ensure we are running the Wrapper, not a test script
    # This matches the "fix" we just applied to the Dockerfile
    docker_cmd = [
        "docker", "run", 
        "--name", CONTAINER_NAME,
        "-p", f"{PORT}:8080",
        *env_vars,
        IMAGE_NAME
    ]
    
    # We use Popen so we can interrupt it later
    return subprocess.Popen(docker_cmd)

def main():
    cleanup_container()
    build_image()
    
    process = run_container()
    
    out(f"\n✅ Container is running on http://localhost:{PORT}")
    out("📋 Streaming logs (Press Ctrl+C to test Graceful Shutdown)...")
    out("-" * 50)

    try:
        # Stream logs efficiently
        subprocess.run(["docker", "logs", "-f", CONTAINER_NAME])
    except KeyboardInterrupt:
        out("\n\n🛑 Received Ctrl+C. Testing SIGTERM handling...")
        
        # Simulate Cloud Run shutting down the instance
        # Cloud Run sends SIGTERM, waits 10s, then kills.
        subprocess.run(["docker", "stop", "-t", "10", CONTAINER_NAME])
        
        out("\n🔎 Verifying Shutdown Logs:")
        out("-" * 20)
        # Fetch the last 20 lines of logs to see if the shutdown message appears
        logs = subprocess.check_output(["docker", "logs", "--tail", "20", CONTAINER_NAME]).decode("utf-8")
        out(logs)
        
        if "Daemon Host: Cleanup complete" in logs or "Application shutdown complete" in logs:
            out("\n✅ SUCCESS: Graceful shutdown detected!")
        else:
            out("\n⚠️ WARNING: Graceful shutdown message NOT found. Check entrypoint_wrapper.py.")

    finally:
        cleanup_container()

if __name__ == "__main__":
    main()