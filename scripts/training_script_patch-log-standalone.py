"""Deliberate missing column: Age_log referenced but not created."""

import pandas as pd
import numpy as np

df = pd.DataFrame({"Age": [25, 30, 35, np.nan, 40], "target": [0, 1, 0, 1, 0]})

# Fix: Create Age_log column before referencing it
df["Age_log"] = np.log(df["Age"])

X = df[["Age", "Age_log"]]
y = df["target"]
print(X.head())
