"""Rule-based quick patches for known ML training errors.
No LLM calls needed — deterministic search/replace, insert, or simple transform.
Every function: (script_content: str, exception_message: str) -> str | None (None = no rule matched, fallback to LLM)."""

import ast
import re
import subprocess
import sys


# ============================================================
# Level 0: Deterministic Repair Rules
# Each function: (script: str, message: str) -> str | None
# ============================================================


def fix_name_error(script: str, message: str) -> str | None:
    name_map = {"false": "False", "true": "True", "null": "None"}
    for js_literal in name_map:
        if js_literal in message.lower():
            script = re.sub(r"\bfalse\b", "False", script)
            script = re.sub(r"\btrue\b", "True", script)
            script = re.sub(r"\bnull\b", "None", script)
            return script
    return None


def fix_import_error(script: str, message: str) -> str | None:
    m = re.search(r"No module named '([^']+)'", message)
    if not m:
        m = re.search(r"cannot import name '([^']+)'", message)
    if not m:
        return None
    package = m.group(1)
    parent = package.split(".")[0]
    install_line = f"subprocess.check_call([sys.executable, '-m', 'pip', 'install', '{parent}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    marker = f"# dissect-import-{parent}"
    if marker in script:
        return script
    if "subprocess" not in script:
        script = f"import subprocess\nimport sys\n{install_line}  {marker}\n" + script
    else:
        script = script.replace(
            "import subprocess\n",
            f"import subprocess\nimport sys\n{install_line}  {marker}\n",
            1,
        )
    return script


# ---- dtype_mismatch: multiple strategy attempts ----


def _find_dataframe_var(script: str) -> str:
    aliases = ["df", "data", "dataset", "train", "X"]
    for alias in aliases:
        if re.search(rf"{alias}\s*=\s*pd\.", script):
            return alias
    return "df"


def _find_preprocessing_insertion_point(script: str) -> int:
    lines = script.split("\n")
    train_call = None
    for i, line in enumerate(lines):
        if any(kw in line for kw in [".fit(", ".fit_transform(", "train_test_split", "model = "]):
            train_call = i
        if "train_test_split" in line:
            return i + 1
    if train_call is not None:
        return train_call
    return len(lines) - 1


def fix_dtype_mismatch(script: str, message: str) -> str | None:
    if (
        "could not convert string" not in message
        and "cannot convert" not in message
        and "dtype" not in message.lower()
        and "type" not in message.lower()
    ):
        return None

    pattern = r"could not convert string to float:\s*'([^']+)'"
    m = re.search(pattern, message)
    bad_value = m.group(1) if m else None

    m2 = re.search(r"'([^']+)'.*dtype", message)
    column_hint = m2.group(1) if m2 else None

    df_var = _find_dataframe_var(script)

    # Strategy 1: Per-column label encoding (most targeted)
    if column_hint:
        enc_block = (
            f"\n\n# [Dissect] Label encode problematic column\n"
            f"from sklearn.preprocessing import LabelEncoder\n"
            f"_le = LabelEncoder()\n"
            f"{df_var}['{column_hint}'] = _le.fit_transform({df_var}['{column_hint}'].astype(str))\n"
        )
        if "LabelEncoder" not in script and f"'{column_hint}'" not in script:
            pos = _find_preprocessing_insertion_point(script)
            lines = script.split("\n")
            lines.insert(pos, enc_block)
            return "\n".join(lines)

    # Strategy 2: Generic object -> numeric coerce
    fix_code = (
        f"\n\n# [Dissect hotfix] Coerce mixed-type columns to numeric\n"
        f"for _col in {df_var}.columns:\n"
        f"    if {df_var}[_col].dtype == 'object':\n"
        f"        {df_var}.loc[:, _col] = pd.to_numeric({df_var}[_col], errors='coerce')\n"
    )
    if "pd.to_numeric" not in script:
        script += fix_code
    return script


# ---- missing_column: derive/rename/drop/abort ----


def _get_target_column(script: str) -> str | None:
    m = re.search(r"['\"]([\w_]+)['\"]\s*[=:].*target|target\s*[=:]\s*['\"]([\w_]+)['\"]", script)
    if m:
        return m.group(1) or m.group(2)
    m = re.search(r"y\s*=\s*(?:df|data|dataset|train)\[['\"]([\w_]+)['\"\]]", script)
    if m:
        return m.group(1)
    return None


def fix_missing_column(script: str, message: str) -> str | None:
    if "not found in" not in message and "not in index" not in message:
        return None

    m = re.search(r"'([^']+)' not found in|['\"](\w+)['\"] not in index", message)
    col_name = m.group(1) if m and m.group(1) else (m.group(2) if m else None)
    if not col_name:
        return None

    df_var = _find_dataframe_var(script)
    target = _get_target_column(script)

    # Try to derive the column from existing columns
    rule_suffixes = [
        ("age", ""),
        ("log_", f"np.log1p({df_var}['{col_name.replace('log_', '')}'] + 1e-8)"),
        (
            "_ratio",
            f"{df_var}['{col_name.replace('_ratio', '_a')}'] / ({df_var}['{col_name.replace('_ratio', '_b')}'] + 1e-8)",
        ),
        (
            "_bin",
            f"pd.qcut({df_var}['{col_name.replace('_bin', '')}'], q=4, labels=False, duplicates='drop')",
        ),
        ("onehot_", f"{df_var}['{col_name.replace('onehot_', '')}']"),
        ("dummy_", f"{df_var}['{col_name.replace('dummy_', '')}']"),
    ]
    for suffix, fix_expr in rule_suffixes:
        if suffix in col_name.lower() and fix_expr:
            insertion = f"\n{df_var}['{col_name}'] = {fix_expr}\n"
            if f"'{col_name}'" not in script:
                lines = script.split("\n")
                last_df_ref = 0
                for i, line in enumerate(lines):
                    if df_var in line and not line.strip().startswith("#"):
                        last_df_ref = i
                lines.insert(last_df_ref + 1, insertion.rstrip())
                return "\n".join(lines)

    # If it's the target column, it's critical - skip for now
    if col_name == target:
        return None

    # Try drop: add .drop(col_name, axis=1) after train_test_split or before fit
    drop_line = f"\n# [Dissect] Drop missing column '{col_name}'\n{df_var} = {df_var}.drop(columns=['{col_name}'], errors='ignore')\n"
    if f".drop(columns=['{col_name}']" not in script:
        lines = script.split("\n")
        for i, line in enumerate(lines):
            if "train_test_split" in line:
                lines.insert(i + 1, drop_line.rstrip())
                return "\n".join(lines)
        script += drop_line
    return script


# ---- sparse_matrix ----


def fix_sparse_matrix(script: str, message: str) -> str | None:
    if "SMOTE" not in message and "sparse" not in message:
        return None
    if "SMOTE" in script and ".toarray()" not in script:
        replace_block = (
            "\n\n# [Dissect] Convert sparse to dense before SMOTE\n"
            "if hasattr(X, 'toarray'):\n"
            "    X = X.toarray()\n"
            "elif hasattr(X, 'todense'):\n"
            "    X = X.todense()\n"
        )
        script += replace_block
    return script


# ---- OOM (CPU) ----


def fix_oom(script: str, message: str) -> str | None:
    if "cannot allocate" not in message and "MemoryError" not in message:
        return None
    fix_lines = [
        "\n# [Dissect] Reduce memory: smaller batch, chunked loading",
        "import gc",
        "",
    ]
    batch_reductions = [
        (r"batch_size\s*=\s*(\d+)", lambda m: f"batch_size = {int(int(m.group(1)) * 0.75)}"),
        (r"batch_size\s*:\s*(\d+)", lambda m: f"batch_size: {int(int(m.group(1)) * 0.75)}"),
        (r'"batch_size":\s*(\d+)', lambda m: f'"batch_size": {int(int(m.group(1)) * 0.75)}'),
    ]
    for pattern, repl in batch_reductions:
        if re.search(pattern, script):
            script = re.sub(pattern, repl, script)
            break
    if "batch_size" not in script and "batch_size" not in script:
        script += "\n# [Dissect] Enable garbage collection\nimport gc\ngc.collect()\n"

    if "gc.collect" in "\n".join(fix_lines):
        return script
    return script + "\n".join(fix_lines)


# ---- CUDA OOM ----


def fix_cuda_oom(script: str, message: str) -> str | None:
    if "CUDA out of memory" not in message and "out of memory" not in message:
        return None

    changes = []

    batch_reductions = [
        (
            r"batch_size\s*=\s*(\d+)",
            lambda m: f"batch_size = {max(1, int(int(m.group(1)) * 0.75))}",
        ),
        (
            r"per_device_train_batch_size\s*=\s*(\d+)",
            lambda m: f"per_device_train_batch_size = {max(1, int(int(m.group(1)) * 0.75))}",
        ),
        (
            r'"batch_size":\s*(\d+)',
            lambda m: f'"batch_size": {max(1, int(int(m.group(1)) * 0.75))}',
        ),
    ]
    for pattern, repl in batch_reductions:
        if re.search(pattern, script):
            script = re.sub(pattern, repl, script)
            changes.append("reduced_batch")
            break

    if "torch.cuda.empty_cache" not in script:
        script = "import torch\ntorch.cuda.empty_cache()\n" + script
        changes.append("empty_cache")

    return script if changes else script + "\ntorch.cuda.empty_cache()\n"


# ---- convergence_failure ----


def fix_convergence_failure(script: str, message: str) -> str | None:
    if "failed to converge" not in message and "convergence" not in message:
        return None

    solver_replacement = [
        (r"max_iter\s*=\s*(\d+)", lambda m: f"max_iter = {max(500, int(int(m.group(1)) * 2))}"),
        (r"'solver'\s*:\s*'lbfgs'", "'solver': 'saga'"),
        (r"solver='lbfgs'", "solver='saga'"),
        (r"solver=\"lbfgs\"", "solver='saga'"),
    ]
    for pattern, repl in solver_replacement:
        if re.search(pattern, script):
            script = re.sub(pattern, repl, script)
            return script

    script = re.sub(r"max_iter\b", "max_iter", script)
    if "max_iter" not in script:
        for model_call in [
            "LogisticRegression",
            "LinearRegression",
            "SGDClassifier",
            "SGDRegressor",
        ]:
            if model_call in script:
                script = script.replace(
                    f"{model_call}(",
                    f"{model_call}(max_iter=1000, ",
                    1,
                )
                break
    return script


# ---- empty_dataset ----


def fix_empty_dataset(script: str, message: str) -> str | None:
    if "zero-size" not in message and "empty" not in message and "0 rows" not in message:
        return None

    fix_block = (
        "\n\n# [Dissect] Ensure non-empty dataset after split\n"
        "import numpy as np\n"
        "if len(X_train) == 0 or len(y_train) == 0:\n"
        "    X_train, X_test, y_train, y_test = train_test_split(\n"
        "        X, y, test_size=0.2, random_state=42, stratify=y if len(np.unique(y)) > 1 else None\n"
        "    )\n"
        "    if len(X_train) == 0:\n"
        "        raise RuntimeError('Dataset empty after split - cannot proceed')\n"
    )
    if "len(X_train) == 0" not in script:
        script += fix_block
    return script


LINE_FIXES = [
    lambda l: l.replace("= =", "==").replace("= ==", "==").replace("! =", "!="),
    lambda l: l.rstrip(",").rstrip(";") if not l.endswith(":") else l,
    lambda l: re.sub(r"(\w+)\s*=\s*(\d+)\s+and\s+", r"\1 == \2 and ", l) if "and" in l else l,
    lambda l: l.replace("NoneType", "type(None)"),
    lambda l: re.sub(r"'([^']*)'\)\s*{", r"'\1'): {", l) if l.strip().endswith("{") else l,
]

# ---- checkpoint_corruption ----


def fix_checkpoint_corruption(script: str, message: str) -> str | None:
    if "invalid load key" not in message and "unpickl" not in message:
        return None

    m = re.search(r"'([^']+)'", message)
    checkpoint_hint = m.group(1) if m else "checkpoint"

    fix_block = (
        f"\n\n# [Dissect] Handle corrupted checkpoint\n"
        f"import os\n"
        f"if os.path.exists('{checkpoint_hint}'):\n"
        f"    try:\n"
        f"        with open('{checkpoint_hint}', 'rb') as _f:\n"
        f"            _ = _f.read(1)\n"
        f"    except Exception:\n"
        f"        os.remove('{checkpoint_hint}')\n"
        f"        print('[Dissect] Removed corrupted checkpoint, starting fresh')\n"
    )
    if "corrupted checkpoint" not in script:
        script = fix_block + script
    return script


# ---- optimizer_divergence ----


def fix_optimizer_divergence(script: str, message: str) -> str | None:
    if (
        "loss" not in message.lower()
        and "nan" not in message.lower()
        and "inf" not in message.lower()
    ):
        return None

    if "learning_rate" in script or "lr" in script:
        script = re.sub(
            r"learning_rate\s*=\s*([\d.]+e?-?\d*)",
            lambda m: f"learning_rate = {float(m.group(1)) * 0.5}",
            script,
        )
        script = re.sub(
            r"lr\s*=\s*([\d.]+e?-?\d*)", lambda m: f"lr = {float(m.group(1)) * 0.5}", script
        )
        script = re.sub(
            r"'lr'\s*:\s*([\d.]+e?-?\d*)", lambda m: f"'lr': {float(m.group(1)) * 0.5}", script
        )

    if "clip_grad" not in script:
        for optimizer in ["Adam", "SGD", "AdamW"]:
            if optimizer in script:
                script += "\n# [Dissect] Add gradient clipping\nfor _group in optimizer.param_groups:\n    _group['max_grad_norm'] = 1.0\n"
                break
    return script


# ---- index_error ----


def fix_index_error(script: str, message: str) -> str | None:
    if "out of bounds" not in message and "out of range" not in message:
        return None
    fix_block = (
        "\n\n# [Dissect] Bounds check before array access\n"
        "def _safe_get(arr, idx):\n"
        "    if idx < len(arr):\n"
        "        return arr[idx]\n"
        "    return arr[-1] if len(arr) > 0 else None\n"
    )
    if "_safe_get" not in script:
        script = fix_block + script
    return script


# ---- label_mismatch ----


def fix_label_mismatch(script: str, message: str) -> str | None:
    if "class" not in message.lower() and "label" not in message.lower():
        return None

    fix_block = (
        "\n\n# [Dissect] Handle label mismatch\n"
        "import numpy as np\n"
        "classes = np.unique(y_train) if 'y_train' in dir() else np.unique(y)\n"
        "if len(classes) < 2:\n"
        "    raise RuntimeError(f'Need >= 2 classes, got {len(classes)}')\n"
    )
    if "classes = np.unique" not in script:
        script += fix_block
    return script


# ---- unseen_label ----
# Fixes LabelEncoder crash when test set contains categories not seen in training.
# Pattern: separate fit_transform per train/test -> unified encoder + fillna(-1)


def fix_unseen_label(script: str, message: str) -> str | None:
    if "new label" not in message.lower() and "unseen label" not in message.lower():
        return None

    # Pattern 1: per-column LabelEncoder with separate fit for train and test
    #   X_train[col] = LabelEncoder().fit_transform(X_train[col])
    #   X_test[col] = LabelEncoder().fit_transform(X_test[col])
    sep_encoder_pattern = re.compile(
        r"(\s+)(\w+)\[col\]\s*=\s*LabelEncoder\(\)\.fit_transform\(\2\[col\]\)\n"
        r"\1\2\[col\]\s*=\s*LabelEncoder\(\)\.fit_transform\(\2\[col\]\)"
    )
    m = sep_encoder_pattern.search(script)
    if m:
        indent = m.group(1)
        df_var = m.group(2)
        replacement = (
            f"{indent}_le = LabelEncoder()\n"
            f"{indent}{df_var}[col] = _le.fit_transform({df_var}[col].astype(str))\n"
            f"{indent}_mapping = {{cls: i for i, cls in enumerate(_le.classes_)}}\n"
            f"{indent}{df_var}[col] = {df_var}[col].astype(str).map(_mapping).fillna(-1).astype(int)"
        )
        script = sep_encoder_pattern.sub(replacement, script)
        return script

    # Pattern 2: OrdinalEncoder or similar with handle_unknown issue
    # Add fallback for test transform
    if "OrdinalEncoder" in script and "handle_unknown" not in script:
        script = script.replace(
            "OrdinalEncoder()",
            'OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)',
        )
        return script

    # Pattern 3: single LabelEncoder.fit_transform(train) then .transform(test)
    # Wrap .transform in try/except and fallback
    # Match: _le = LabelEncoder() ... _le.transform(X_test) or similar
    le_transform_pattern = re.compile(r"(\.transform\()")
    if "LabelEncoder" in script and le_transform_pattern.search(script):
        replacement = (
            "\n# [Dissect] Handle unseen labels in transform\n"
            "import pandas as pd\n"
            "def _safe_transform(encoder, data):\n"
            "    _mapping = {cls: i for i, cls in enumerate(encoder.classes_)}\n"
            "    result = pd.Series(data).astype(str).map(_mapping).fillna(-1).astype(int)\n"
            "    return result.values if hasattr(data, 'shape') else result\n"
        )
        script = replacement + script
        script = _replace_transform_calls(script)
        return script

    return None


def _replace_transform_calls(script: str) -> str:
    """Replace _le.transform(X) with _safe_transform(_le, X) for LabelEncoder calls."""
    result = []
    lines = script.split("\n")
    in_encoder_block = False
    encoder_var = None
    for line in lines:
        m = re.match(r"^(\s*)(\w+)\s*=\s*LabelEncoder\(\)", line)
        if m:
            in_encoder_block = True
            encoder_var = m.group(2)
            result.append(line)
            continue
        if in_encoder_block and encoder_var:
            # Replace transform calls on this encoder
            if f"{encoder_var}.transform(" in line:
                line = re.sub(
                    rf"{encoder_var}\.transform\(([^)]+)\)",
                    rf"_safe_transform({encoder_var}, \1)",
                    line,
                )
            elif not line.strip().startswith(encoder_var) and encoder_var not in line:
                in_encoder_block = False
                encoder_var = None
        result.append(line)
    return "\n".join(result)


# ---- better syntax_error: AST-based ----


def _ast_fix_script(script: str) -> str | None:
    try:
        ast.parse(script)
        return None
    except SyntaxError:
        pass

    lines = script.split("\n")
    for i in range(len(lines) - 1, -1, -1):
        for fix in LINE_FIXES:
            fixed = fix(lines[i])
            if fixed != lines[i]:
                old = lines[i]
                lines[i] = fixed
                try:
                    ast.parse("\n".join(lines))
                    return "\n".join(lines)
                except SyntaxError:
                    lines[i] = old
    return None


def fix_syntax_error(script: str, message: str) -> str | None:
    # Strategy 1: AST-based fix (most general)
    ast_result = _ast_fix_script(script)
    if ast_result is not None:
        return ast_result

    # Strategy 2: Positional argument follows keyword
    if "positional argument follows keyword" in message:
        lines = script.split("\n")
        fixed = []
        for line in lines:
            if "(" not in line or ")" not in line:
                fixed.append(line)
                continue
            open_paren = line.find("(")
            close_paren = line.rfind(")")
            if open_paren == -1 or close_paren <= open_paren:
                fixed.append(line)
                continue
            before_paren = line[: open_paren + 1]
            after_paren = line[close_paren:]
            args_str = line[open_paren + 1 : close_paren]
            args = [a.strip() for a in re.split(r",\s*(?![^()]*\))", args_str) if a.strip()]

            positional = []
            positional_unpack = []
            keyword = []
            keyword_unpack = []
            for arg in args:
                if arg.startswith("**"):
                    keyword_unpack.append(arg)
                elif arg.startswith("*"):
                    positional_unpack.append(arg)
                elif "=" in arg and not arg.startswith(("**", "*")):
                    keyword.append(arg)
                else:
                    positional.append(arg)

            reordered = positional + positional_unpack + keyword + keyword_unpack
            fixed.append(before_paren + ", ".join(reordered) + after_paren)
        result = "\n".join(fixed)
        try:
            ast.parse(result)
            return result
        except SyntaxError:
            pass

    # Strategy 3: Add missing closing bracket
    if "unexpected EOF" in message or "EOL while scanning" in message:
        opens = script.count("(") + script.count("[") + script.count("{")
        closes = script.count(")") + script.count("]") + script.count("}")
        if opens > closes:
            script += "\n" + ")" * (opens - closes)
            return script

    return None


# ---- Legacy rules that survived unchanged ----


def fix_nan_propagation(script: str, message: str) -> str | None:
    if "NaN" not in message and "missing values" not in message:
        return None
    fix_code = (
        "\n\n# [Dissect hotfix] Impute NaN values before training\n"
        "from sklearn.impute import SimpleImputer\n"
        "numeric_cols = X.select_dtypes(include=['number']).columns\n"
        "categorical_cols = X.select_dtypes(include=['object']).columns\n"
        "if len(numeric_cols):\n"
        "    imputer_num = SimpleImputer(strategy='median')\n"
        "    X[numeric_cols] = imputer_num.fit_transform(X[numeric_cols])\n"
        "if len(categorical_cols):\n"
        "    imputer_cat = SimpleImputer(strategy='most_frequent')\n"
        "    X[categorical_cols] = imputer_cat.fit_transform(X[categorical_cols])\n"
    )
    if "SimpleImputer" not in script:
        script += fix_code
    return script


def fix_zero_division(script: str, message: str) -> str | None:
    if "division by zero" not in message and "divide by zero" not in message:
        return None
    script = re.sub(r"(\w+)\s*/\s*(\w+)", r"\1 / (\2 + 1e-8)", script)
    return script


def fix_permission_error(script: str, message: str) -> str | None:
    if "permission denied" not in message.lower() and "access is denied" not in message.lower():
        return None
    m = re.search(r"'([^']+)'", message)
    path = m.group(1) if m else "."
    fix_code = f"\nimport os\nos.makedirs('{path}', exist_ok=True)\n"
    if f"makedirs('{path}'" not in script:
        script = fix_code + script
    return script


# ---- Master rule registry ----

RULES: dict[str, callable] = {
    "name_error": fix_name_error,
    "import_error": fix_import_error,
    "dtype_mismatch": fix_dtype_mismatch,
    "missing_column": fix_missing_column,
    "nan_propagation": fix_nan_propagation,
    "zero_division": fix_zero_division,
    "permission_error": fix_permission_error,
    "syntax_error": fix_syntax_error,
    "sparse_matrix": fix_sparse_matrix,
    "oom": fix_oom,
    "cuda_oom": fix_cuda_oom,
    "convergence_failure": fix_convergence_failure,
    "empty_dataset": fix_empty_dataset,
    "checkpoint_corruption": fix_checkpoint_corruption,
    "optimizer_divergence": fix_optimizer_divergence,
    "index_error": fix_index_error,
    "label_mismatch": fix_label_mismatch,
    "unseen_label": fix_unseen_label,
}


def apply_rule(category: str, script: str, message: str) -> str | None:
    fn = RULES.get(category)
    if fn:
        return fn(script, message)
    return None
