import pandas as pd
import numpy as np

class OmniQuantAI:
    """
    Autonomous AI trading agent that detects market regimes
    and selects trading strategies accordingly.
    """
    def __init__(self):
        pass

    def detect_regime(self, data):
        """Detect market regime based on volatility"""
        volatility = data['Close'].pct_change().rolling(window=3).std().iloc[-1]
        if volatility > 0.02:
            return "High Volatility"
        else:
            return "Stable"

    def select_strategy(self, regime):
        """Select strategy based on market regime"""
        if regime == "High Volatility":
            return "Mean Reversion"
        else:
            return "Trend Following"

    def generate_signals(self, data):
        """Generate trading signals based on strategy"""
        regime = self.detect_regime(data)
        strategy = self.select_strategy(regime)
        print(f"Detected Regime: {regime}, Selected Strategy: {strategy}")
        signals = np.sign(data['Close'].diff().fillna(0))
        return signals
