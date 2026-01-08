# Alpaca API Credentials ToDo

The Alpaca API credentials (APCA_API_KEY_ID and APCA_API_SECRET_KEY) in your `.env.local` file are invalid, resulting in a 401 Unauthorized error when attempting to access the Alpaca API.

Please ensure you have the correct Alpaca paper trading API keys set in your `.env.local` file.

Example:
`APCA_API_KEY_ID="PK.................."`
`APCA_API_SECRET_KEY="SK................................................."`

This issue blocks placing test orders.
