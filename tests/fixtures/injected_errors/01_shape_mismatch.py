"""Deliberate shape mismatch: fit on 5 features, transform on 4."""

import pandas as pd
from sklearn.preprocessing import LabelEncoder

df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6], "d": [7, 8], "e": ["x", "y"]})
le = LabelEncoder()
df["e"] = le.fit_transform(df["e"])

# Bug: transform on only 4 columns (missing "e")
X_train = df[["a", "b", "c", "d"]]
X_test = df[["a", "b", "c"]]  # Missing column "d" ? will cause shape mismatch
print(X_train.shape[1], X_test.shape[1])
