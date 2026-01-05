import streamlit as st
import pandas as pd
import numpy as np
import plotly.figure_factory as ff
from backend.services.whale_flow import get_recent_conviction
from decimal import Decimal

def display_dealer_transition_zones():
    """Displays dynamic Dealer Transition Zones."""
    st.header("Dealer Transition Zones")
    ptrans = np.random.uniform(4500, 5500)
    ntrans = np.random.uniform(-4500, -5500)
    st.metric(label="PTrans (Positive Transition)", value=f"${ptrans:,.2f}")
    st.metric(label="NTrans (Negative Transition)", value=f"${ntrans:,.2f}")

def display_whale_flow():
    """Displays the Whale Flow Alert Feed."""
    st.header("Whale Flow Alert Feed")
    
    # Get recent conviction for a default ticker
    whale_flow_data = get_recent_conviction(uid="user123", ticker="SPY", lookback_minutes=60)

    if whale_flow_data['has_activity']:
        st.metric(label="Conviction Score", value=f"{whale_flow_data['avg_conviction']:.2f}")
        st.metric(label="Total Premium", value=f"${whale_flow_data['total_premium']:,.2f}")
        st.metric(label="Dominant Sentiment", value=whale_flow_data['dominant_sentiment'])
    else:
        st.info("No recent whale activity for SPY.")

def display_regime_status():
    """Displays the current market regime status."""
    st.header("Regime Status")
    regime = np.random.choice(["Volatile/Negative Gamma", "Stable/Positive Gamma"])
    st.metric(label="Current Regime", value=regime)

def main():
    """Main function for the Streamlit dashboard."""
    st.title("AgentTrader Live Dashboard")

    display_dealer_transition_zones()
    st.divider()
    display_whale_flow()
    st.divider()
    display_regime_status()

if __name__ == "__main__":
    main()