# Alpaca API Credentials ToDo

The Alpaca API credentials (ALPACA_KEY_ID and ALPACA_SECRET_KEY) in your `.env.local` file are invalid, resulting in a 401 Unauthorized error when attempting to access the Alpaca API.

Please ensure you have the correct Alpaca paper trading API keys set in your `.env.local` file.

Example:
`ALPACA_KEY_ID="PK.................."`
`ALPACA_SECRET_KEY="SK................................................."`

This issue blocks placing test orders.
