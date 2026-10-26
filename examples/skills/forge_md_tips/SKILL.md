---
name: forge_md_tips
version: "1.0.0"
description: Instruction skill — coding conventions Forge must follow when generating a training script
category: guidance
agents: [forge]
type: instruction
requires_llm: true
---
# Forge script conventions

When you generate a training script for this job, follow these rules:

1. **Label-encode categoricals first.** Every categorical feature column must be
   passed through `LabelEncoder` (or equivalent) before the model sees it. Never
   hand a raw string column to the estimator.
2. **Impute before you encode.** Handle missing values *before* any encoding or
   scaling step, so the encoders never observe NaN.
3. **Prefer LightGBM for tabular data under ~1M rows** with the job's evaluation
   metric as `objective`/`metric`; fall back to XGBoost only if LightGBM is
   unavailable.
4. **Emit structured progress.** Print a JSON line per epoch with keys
   `epoch`, `loss`, `metric`, `elapsed_s` so the Furnace stream can parse it.
5. **Never fit on the test split.** Split the data once at the top; everything
   downstream trains on the training split only.
