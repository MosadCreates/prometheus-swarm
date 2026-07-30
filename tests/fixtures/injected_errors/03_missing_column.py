"""Minimal LightGBM training script with an intentional missing column bug.
Age_log is referenced but never derived from Age."""

import json
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
import lightgbm as lgb

df = pd.DataFrame(
    {
        "Age": [25, 30, 35, np.nan, 40, 22, 28, 33, 27, 45, 31, 29],
        "target": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
    }
)

# Bug: Age_log column referenced but never created
X = df[["Age", "Age_log"]]
y = df["target"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = lgb.LGBMClassifier(n_estimators=10, max_depth=3, verbose=-1)
model.fit(X_train, y_train)

from sklearn.metrics import roc_auc_score

preds = model.predict_proba(X_test)[:, 1]
score = roc_auc_score(y_test, preds)

with open("result.json", "w") as f:
    json.dump({"val_score": float(score)}, f)
print("TRAINING_COMPLETE")
