import matplotlib.pyplot as plt
import seaborn as sns

sns.set(style="whitegrid")

def plot_signals(data, signals, title="Trading Signals"):
    plt.figure(figsize=(12,6))
    plt.plot(data['Date'], data['Close'], label="Price", color='blue')
    plt.scatter(data['Date'], data['Close'], c=signals, cmap='coolwarm', label="Signals", marker='o')
    plt.title(title)
    plt.xlabel("Date")
    plt.ylabel("Price")
    plt.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()
