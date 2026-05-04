import numpy as np

def backtest(preds, y_true):
    preds = np.array(preds)
    y_true = np.array(y_true)

    positions = np.sign(preds)
    returns = positions * y_true

    equity = np.cumprod(1 + returns)

    sharpe = np.mean(returns) / (np.std(returns) + 1e-9) * np.sqrt(252)
    total_return = equity[-1] - 1
    max_dd = np.min(equity / np.maximum.accumulate(equity) - 1)

    return {
        "equity": equity,
        "sharpe": sharpe,
        "return": total_return,
        "max_dd": max_dd
    }