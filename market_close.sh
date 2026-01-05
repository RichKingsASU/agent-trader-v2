#!/bin/bash
echo "--- MARKET CLOSE ---"
# This is a placeholder for actual market close commands.
# For example, you might trigger a process to flatten all positions.
pkill -f "python3 functions/maestro_bridge.py"
pkill -f "streamlit run functions/dashboard.py"
echo "Maestro Bridge and Streamlit dashboard have been shut down."