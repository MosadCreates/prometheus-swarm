"""Deliberate NaN propagation: no fillna applied."""

import pandas as pd
from sklearn.linear_model import LinearRegression

df = pd.DataFrame(
    {
        "Age": [25, 30, None, 35, None, 40],
        "Income": [50000, 60000, 55000, 65000, None, 70000],
        "target": [100, 200, 150, 250, 180, 300],
    }
)

# Bug: no fillna ? NaN values propagate to model
X = df[["Age", "Income"]]
y = df["target"]

model = LinearRegression()
model.fit(X, y)  # Will fail: Input contains NaN
