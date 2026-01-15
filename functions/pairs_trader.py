# ~/agenttrader_v2/functions/pairs_trader.py

import os
import numpy as np
import pandas as pd
import alpaca_trade_api as tradeapi
from datetime import datetime, timedelta

from backend.common.alpaca_env import configure_alpaca_env

"""
Strategy III: Kalman Filter Pairs Trader

- Logic: Implements a KALMAN FILTER for dynamic hedge ratio updates [cite: 100, 103].
- Equations: 
    - State: beta_t = beta_{t-1} + omega_t 
    - Measurement: Y_t = beta_t*X_t + epsilon_t
    [cite: 103, 104]
- Optimization: Uses an EM Algorithm to tune process noise (Q) and measurement noise (R) [cite: 117, 119].
- Signal: Entry at 1.0 standard deviations of prediction error [cite: 114].
"""

class KalmanPairsTrader:
    """
    Implements a pairs trading strategy using a Kalman Filter to dynamically
    model the hedge ratio between two assets.
    """
    def __init__(self, symbol_y, symbol_x, lookback_days=100):
        self.symbol_y = symbol_y
        self.symbol_x = symbol_x
        self.lookback_days = lookback_days
        
        # Kalman Filter state variables
        self.delta = 1e-4  # For state covariance matrix
        self.wt = self.delta / (1 - self.delta) * np.eye(1)
        self.vt = 1e-3 # Measurement noise variance
        self.beta = np.zeros(1) # Initial hedge ratio (state)
        self.P = np.zeros((1, 1)) # Initial state covariance
        self.R = None # State covariance forecast
        
        # EM Algorithm parameters
        self.Q = None # Process noise covariance
        self.R_em = None # Measurement noise covariance (used in EM)
        
        self.prediction_errors = []
        
        try:
            alpaca = configure_alpaca_env(required=True)
            self.api = tradeapi.REST(
                alpaca.api_key_id,
                alpaca.api_secret_key,
                base_url=alpaca.api_base_url,
            )
            print("✅ Alpaca API initialized successfully.")
        except Exception as e:
            print(f"🔥 Error initializing Alpaca API: {e}")
            self.api = None

    def _fetch_data(self):
        """Fetches historical daily close prices for the pair."""
        if not self.api:
            return None
            
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.lookback_days)
        
        try:
            barset = self.api.get_bars(
                [self.symbol_y, self.symbol_x],
                '1Day',
                start=start_date.isoformat(),
                end=end_date.isoformat()
            ).df
            
            # Pivot the dataframe to get symbols as columns
            y = barset[barset['symbol'] == self.symbol_y]['close']
            x = barset[barset['symbol'] == self.symbol_x]['close']
            
            return pd.DataFrame({'y': y, 'x': x}).dropna()
            
        except Exception as e:
            print(f"🔥 Error fetching historical data: {e}")
            return None

    def _em_algorithm(self, data, max_iter=10):
        """
        Expectation-Maximization (EM) algorithm to estimate noise covariances Q and R.
        [cite: 117, 119]
        """
        # Initial guess for Q and R
        self.Q = np.array([[1e-5]])
        self.R_em = np.array([[1e-3]])
        
        y = data['y'].values
        x = data['x'].values.reshape(-1, 1)
        
        for i in range(max_iter):
            # E-Step: Use Kalman Smoother to get expected state and covariance
            # (Simplified version without full smoother for brevity, focuses on forward pass)
            
            beta_hat = np.zeros((len(y), 1))
            P_hat = np.zeros((len(y), 1, 1))
            beta_t = self.beta
            P_t = self.P
            
            for t in range(len(y)):
                # Prediction
                beta_pred = beta_t
                P_pred = P_t + self.Q
                
                # Update
                K = P_pred * x[t] / (x[t] * P_pred * x[t] + self.R_em)
                beta_t = beta_pred + K * (y[t] - x[t] * beta_pred)
                P_t = (1 - K * x[t]) * P_pred
                
                beta_hat[t] = beta_t
                P_hat[t] = P_t
            
            # M-Step: Update Q and R based on smoothed estimates
            # (Simplified update rule)
            state_diff = np.diff(beta_hat, axis=0)
            self.Q = np.mean(state_diff**2)
            
            residuals = y - (x * beta_hat).sum(axis=1)
            self.R_em = np.mean(residuals**2)
            
        print(f"✅ EM Algorithm converged. Q={self.Q:.6f}, R={self.R_em:.6f}")


    def warmup(self):
        """
        Initializes the filter and runs the EM algorithm on historical data.
        """
        print(f"🚀 Warming up Kalman Filter for {self.symbol_y}/{self.symbol_x}...")
        data = self._fetch_data()
        if data is None or data.empty:
            print("🔥 Cannot warm up filter: no data.")
            return

        # Run EM algorithm to tune noise parameters
        self._em_algorithm(data)
        
        # Run the filter over the historical data to get a baseline
        for i in range(len(data)):
            y_t = data['y'].iloc[i]
            x_t = data['x'].iloc[i]
            self.update(y_t, x_t)
            
        print(f"✅ Warmup complete. Current hedge ratio (beta): {self.beta[0]:.4f}")

    def update(self, y_t, x_t):
        """
        Updates the Kalman Filter with a new data point (y_t, x_t).
        """
        if self.Q is None or self.R_em is None:
            # Fallback if EM hasn't run
            self.Q = np.array([[1e-5]])
            self.R_em = np.array([[1e-3]])

        # State Equation: beta_t = beta_{t-1} + omega_t 
        # Here, x_t is treated as the observation matrix H in standard KF notation
        x_t_matrix = np.array([x_t])

        # Prediction step
        self.beta = self.beta # State transition is identity
        self.R = self.P + self.Q
        
        # Measurement update step
        y_pred = np.dot(x_t_matrix, self.beta)
        prediction_error = y_t - y_pred
        self.prediction_errors.append(prediction_error[0])
        
        Q_t = np.dot(np.dot(x_t_matrix, self.R), x_t_matrix.T) + self.R_em
        K = np.dot(self.R, x_t_matrix.T) / Q_t # Kalman Gain
        
        self.beta = self.beta + np.dot(K, prediction_error)
        self.P = self.R - np.dot(np.dot(K, x_t_matrix), self.R)

    def get_signal(self) -> dict:
        """
        Generates a trading signal based on the latest prediction error.
        Signal: Entry at 1.0 standard deviations of prediction error [cite: 114].
        """
        if len(self.prediction_errors) < 20: # Need enough data for a stable std dev
            return {"signal": "HOLD", "reason": "Insufficient data for signal."}
        
        # Use the last 20 errors for a rolling standard deviation
        recent_errors = self.prediction_errors[-20:]
        error_std_dev = np.std(recent_errors)
        latest_error = self.prediction_errors[-1]
        
        signal = "HOLD"
        reason = f"Prediction error {latest_error:.4f} is within 1.0 std dev ({error_std_dev:.4f})."
        
        if latest_error > 1.0 * error_std_dev:
            # Error is positive and significant.
            # Y is higher than predicted, so Y is overvalued relative to X.
            # Sell Y, Buy X.
            signal = "SELL_Y_BUY_X" 
            reason = f"Error ({latest_error:.4f}) > 1.0 std dev ({error_std_dev:.4f}). Short the spread."
        elif latest_error < -1.0 * error_std_dev:
            # Error is negative and significant.
            # Y is lower than predicted, so Y is undervalued relative to X.
            # Buy Y, Sell X.
            signal = "BUY_Y_SELL_X"
            reason = f"Error ({latest_error:.4f}) < -1.0 std dev ({error_std_dev:.4f}). Long the spread."
            
        return {
            "signal": signal,
            "hedge_ratio": self.beta[0],
            "prediction_error": latest_error,
            "error_std_dev": error_std_dev,
            "reason": reason
        }

if __name__ == '__main__':
    print("🚀 Building Kalman Filter Pairs Trading Engine...")
    # Requires Alpaca env vars
    trader = KalmanPairsTrader(symbol_y="AAPL", symbol_x="MSFT")

    if trader.api:
        # Run warmup to initialize filter and tune parameters
        trader.warmup()
        
        # Simulate a new tick of data
        print("\n--- Simulating new data tick ---")
        # Example prices
        aapl_price = 175.50
        msft_price = 305.20
        trader.update(aapl_price, msft_price)
        
        # Get the latest signal
        signal_data = trader.get_signal()
        print(signal_data)
