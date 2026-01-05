#!/bin/bash
echo "--- MARKET OPEN ---"
# Start the maestro bridge to orchestrate the trading processes
python3 functions/maestro_bridge.py &
echo "Maestro Bridge started in the background."

# Start the Streamlit dashboard
streamlit run functions/dashboard.py &
echo "Streamlit dashboard started in the background on port 8501."