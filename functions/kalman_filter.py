
import numpy as np
import yfinance as yf

class KalmanFilter:
    """
    A simple Kalman Filter for estimating the hedge ratio in pairs trading.
    """
    def __init__(self, delta=1e-3, R=1e-3):
        self.delta = delta
        self.R = R
        self.P = 1.0
        self.beta = np.nan

    def update(self, x, y):
        """
        Update the Kalman Filter with a new observation.
        """
        # Prediction step
        self.P = self.P + self.delta

        # Measurement update step
        K = self.P / (self.P + self.R)
        self.beta = self.beta + K * (y - self.beta * x)
        self.P = (1 - K) * self.P

def main():
    """
    Main function for the Kalman Filter example.
    """
    # Fetch data for AAPL and MSFT
    aapl = yf.Ticker("AAPL").history(period="60d")['Close']
    msft = yf.Ticker("MSFT").history(period="60d")['Close']

    kf = KalmanFilter()
    hedge_ratios = []

    for i in range(len(aapl)):
        if np.isnan(kf.beta):
            # Initialize beta with the first observation
            kf.beta = aapl.iloc[i] / msft.iloc[i]
        kf.update(msft.iloc[i], aapl.iloc[i])
        hedge_ratios.append(kf.beta)

    print("Kalman Filter Hedge Ratios:")
    print(hedge_ratios[-5:]) # Print the last 5 hedge ratios

if __name__ == "__main__":
    main()
