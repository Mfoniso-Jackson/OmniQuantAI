import pandas as pd
from strategy import OmniQuantAI
from utils.plotting import plot_signals

# Load sample data
data = pd.read_csv("data/sample_data.csv")

# Initialize AI agent
agent = OmniQuantAI()

# Generate signals
signals = agent.generate_signals(data)

# Plot signals
plot_signals(data, signals, title="OmniQuant AI Backtest")
