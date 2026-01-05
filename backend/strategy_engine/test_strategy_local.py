import asyncio
from .driver import run_strategy

async def main():
    """
    Runs the strategy engine in dry-run mode for local testing.
    """
    print("--- Running Strategy Engine in Dry-Run Mode ---")
    await run_strategy(execute=False)
    print("--- Strategy Engine Dry-Run Complete ---")

if __name__ == "__main__":
    # Ensure DATABASE_URL is set
    import os
    if "DATABASE_URL" not in os.environ:
        print("Error: DATABASE_URL environment variable not set.")
        print("Please set it before running the test.")
    else:
        asyncio.run(main())