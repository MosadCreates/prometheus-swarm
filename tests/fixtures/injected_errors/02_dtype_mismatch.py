"""Deliberate dtype mismatch: string column not encoded."""

import pandas as pd
from sklearn.linear_model import LogisticRegression

df = pd.DataFrame(
    {
        "Age": [25, 30, 35, 40],
        "Sex": ["M", "F", "M", "F"],  # String column ? needs encoding
        "target": [0, 1, 0, 1],
    }
)

X = df[["Age", "Sex"]]
y = df["target"]

model = LogisticRegression()
model.fit(X, y)  # Will fail: could not convert string to float
