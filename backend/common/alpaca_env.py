import os

from backend.common.secrets import get_secret


def configure_alpaca_env() -> None:
    """
    Configure Alpaca SDK environment variables using Secret Manager.

    Sets:
      - APCA_API_KEY_ID
      - APCA_API_SECRET_KEY
      - APCA_API_BASE_URL

    Controlled by:
      ALPACA_ENV = "paper" | "prod" (default: paper)
    """

    env = os.getenv("ALPACA_ENV", "paper").lower()

    if env == "prod":
        key = get_secret("ALPACA_PROD_KEY_ID", allow_env_fallback=False)
        secret = get_secret("ALPACA_PROD_SECRET_KEY", allow_env_fallback=False)
        url = get_secret("ALPACA_PROD_URL", allow_env_fallback=False)

    elif env == "paper":
        key = get_secret("ALPACA_SAND_KEY_ID", allow_env_fallback=False)
        secret = get_secret("ALPACA_SAND_SECRET_KEY", allow_env_fallback=False)
        url = get_secret("ALPACA_SAND_URL", allow_env_fallback=False)

    else:
        raise RuntimeError(f"Invalid ALPACA_ENV: {env}")

    if not all([key, secret, url]):
        raise RuntimeError(f"Missing Alpaca secrets for env: {env}")

    os.environ["APCA_API_KEY_ID"] = key
    os.environ["APCA_API_SECRET_KEY"] = secret
    os.environ["APCA_API_BASE_URL"] = url

