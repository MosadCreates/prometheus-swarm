"""Deliberate import error: non-existent module."""

from fake_ml_library_xyz import SuperModel  # Will fail: No module named

import pandas as pd

df = pd.DataFrame({"x": [1, 2, 3], "y": [0, 1, 0]})
model = SuperModel()
model.fit(df[["x"]], df["y"])
print("Done")
