import os
import sys
import logging
from scripts.lib.alpaca_env_guard import validate_and_correct_alpaca_base_url

# Configure basic logging for the script and imported modules to see helper logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

try:
    corrected_url = validate_and_correct_alpaca_base_url()
    print(f"Function returned: {corrected_url}")
    # Check os.environ directly to see if it was updated
    print(f"os.environ['APCA_API_BASE_URL'] is now: {os.environ.get('APCA_API_BASE_URL')}")
except SystemExit as e:
    print(f"Script exited with error: {e}", file=sys.stderr)
except Exception as e:
    print(f"An unexpected error occurred: {e}", file=sys.stderr)
