import os
import logging
from dotenv import dotenv_values, set_key

logger = logging.getLogger(__name__)

def validate_and_correct_alpaca_base_url():
    """
    Reads APCA_API_BASE_URL from environment variables, validates and corrects it
    according to safety requirements, and applies the corrected value back to
    os.environ. Optionally persists the corrected value to .env.local.

    Raises SystemExit with a clear error message if validation fails.
    """
    original_url = os.getenv("APCA_API_BASE_URL")
    corrected_url = original_url

    logger.info(f"APCA_API_BASE_URL: Original value: '{original_url}'")

    if not original_url:
        logger.error("APCA_API_BASE_URL is not set.")
        raise SystemExit("ERROR: APCA_API_BASE_URL must be set in environment or .env.local.")

    # 1. Strip "/v2" or "/v2/" if at the end
    if corrected_url.endswith("/v2/"):
        corrected_url = corrected_url[:-4]
    elif corrected_url.endswith("/v2"):
        corrected_url = corrected_url[:-3]

    # 2. Check for "/v2" anywhere else
    if "/v2" in corrected_url:
        logger.error(f"APCA_API_BASE_URL contains '/v2' at an unexpected position: '{original_url}'")
        raise SystemExit("ERROR: APCA_API_BASE_URL should not contain '/v2' except as an optional trailing segment.")

    # 3. Enforce https://paper-api.alpaca.markets prefix
    expected_prefix = "https://paper-api.alpaca.markets"
    if not corrected_url.startswith(expected_prefix):
        logger.error(f"APCA_API_BASE_URL must start with '{expected_prefix}'. Found: '{original_url}'")
        raise SystemExit(f"ERROR: APCA_API_BASE_URL must be a paper trading URL: '{expected_prefix}'")

    # If the URL is just the prefix, ensure it is exactly that
    if corrected_url == expected_prefix:
        final_url = expected_prefix
    elif corrected_url == expected_prefix + "/": # Handle cases like https://paper-api.alpaca.markets/
        final_url = expected_prefix
    else:
        # If there's anything else, it's not expected for a simple base URL
        logger.error(f"APCA_API_BASE_URL has unexpected characters after the required prefix: '{original_url}'")
        raise SystemExit(f"ERROR: APCA_API_BASE_URL must be exactly '{expected_prefix}' or '{expected_prefix}/' (after stripping /v2).")

    # Apply the corrected value back into os.environ
    if os.getenv("APCA_API_BASE_URL") != final_url:
        os.environ["APCA_API_BASE_URL"] = final_url
        logger.info(f"APCA_API_BASE_URL: Corrected value applied to os.environ: '{final_url}'")
    else:
        logger.info(f"APCA_API_BASE_URL: Value in os.environ is already correct: '{final_url}'")


    # Optionally persist the corrected value back to .env.local
    dotenv_file_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env.local')
    persistence_occurred = False
    if os.path.exists(dotenv_file_path):
        current_env_values = dotenv_values(dotenv_file_path)
        if current_env_values.get("APCA_API_BASE_URL") != final_url:
            set_key(dotenv_file_path, "APCA_API_BASE_URL", final_url)
            persistence_occurred = True
            logger.info(f"APCA_API_BASE_URL: Persisted corrected value to .env.local: '{final_url}'")
        else:
            logger.info("APCA_API_BASE_URL: Value in .env.local is already correct. No persistence needed.")
    else:
        logger.info(".env.local not found. Skipping persistence of APCA_API_BASE_URL.")

    return final_url
