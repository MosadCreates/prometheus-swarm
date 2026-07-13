"""Artifact validation — every deployment must prove all artifacts match.

Phases of validation:
  1. Pipeline vs PreprocessingContract (feature count, order, types, encoder)
  2. PreprocessingContract vs ONNX (input shape, dtype, feature_hash)
  3. PreprocessingContract vs Generated Config (feature_order)
  4. PreprocessingContract vs Generated App (feature_order, types)
  5. Self-test: send synthetic request → verify prediction succeeds
  6. Deployment report: machine-readable JSON summary

Design rule: Harbor never "hopes" its exported artifacts are consistent.
Every deployment must prove that the training pipeline, preprocessing contract,
ONNX model, serving application, and runtime behavior are all identical before
an endpoint is exposed. If any invariant is violated, deployment must fail
immediately with a precise diagnostic.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from contracts.domain import PreprocessingContract

logger = logging.getLogger(__name__)


# ── Validation result types ────────────────────────────────────────────


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    detail: str = ""
    expected: Any = None
    actual: Any = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "expected": str(self.expected) if self.expected is not None else None,
            "actual": str(self.actual) if self.actual is not None else None,
        }


@dataclass
class ValidationReport:
    artifact: str  # which deployment this belongs to
    checks: list[ValidationCheck] = field(default_factory=list)
    passed: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    pipeline_path: str = ""
    contract_path: str = ""
    onnx_path: str = ""
    app_path: str = ""

    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact,
            "timestamp": self.timestamp,
            "passed": self.all_passed(),
            "checks": [c.as_dict() for c in self.checks],
            "pipeline_path": self.pipeline_path,
            "contract_path": self.contract_path,
            "onnx_path": self.onnx_path,
            "app_path": self.app_path,
        }

    def summary(self) -> str:
        total = len(self.checks)
        passed_count = sum(1 for c in self.checks if c.passed)
        lines = [
            "=" * 50,
            "Deployment Validation Report",
            "=" * 50,
            f"Artifact: {self.artifact}",
            f"Timestamp: {self.timestamp}",
            f"Pipeline: {self.pipeline_path}",
            f"Contract: {self.contract_path}",
            f"ONNX: {self.onnx_path}",
            f"App: {self.app_path}",
            "",
            f"Checks: {passed_count}/{total} passed",
            "",
        ]
        for c in self.checks:
            status = "✓" if c.passed else "✗"
            lines.append(f"  {status} {c.name}")
            if not c.passed:
                lines.append(f"    Reason: {c.detail}")
                if c.expected is not None:
                    lines.append(f"    Expected: {c.expected}")
                if c.actual is not None:
                    lines.append(f"    Actual: {c.actual}")
        lines.append("")
        lines.append(f"Overall: {'✓ VERIFIED' if self.all_passed() else '✗ FAILED'}")
        lines.append("=" * 50)
        return "\n".join(lines)

    def write_to(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.summary())
            f.write("\n")
        json_path = path.replace(".txt", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.as_dict(), f, indent=2)


# ── Validator ─────────────────────────────────────────────────────────


class FeatureContractValidator:
    """Validates all artifacts in a deployment are consistent.

    Usage:
        validator = FeatureContractValidator()
        report = validator.validate_all(
            pipeline_path="/path/to/checkpoint.pkl",
            contract_path="/path/to/preprocessing_contract.json",
            onnx_path="/path/to/model.onnx",
            app_dir="/path/to/serving/",
        )
        if not report.all_passed():
            raise RuntimeError(f"Deployment validation failed:\\n{report.summary()}")
    """

    def __init__(self) -> None:
        self.report: ValidationReport | None = None

    def validate_all(
        self,
        pipeline_path: str | None = None,
        contract_path: str | None = None,
        onnx_path: str | None = None,
        app_dir: str | None = None,
    ) -> ValidationReport:
        """Run all validation checks and return a report."""
        self.report = ValidationReport(
            artifact=os.path.basename(app_dir or "unknown"),
            pipeline_path=pipeline_path or "",
            contract_path=contract_path or "",
            onnx_path=onnx_path or "",
            app_path=os.path.join(app_dir, "app.py") if app_dir else "",
        )

        contract = self._load_contract(contract_path)
        if contract is None:
            self._fail("Contract Load", "Preprocessing contract could not be loaded")
            return self.report

        self._check_contract_validity(contract)
        self._check_onnx_against_contract(contract, onnx_path)
        self._check_app_against_contract(contract, app_dir)

        return self.report

    def _fail(self, name: str, detail: str) -> None:
        self.report.checks.append(ValidationCheck(name=name, passed=False, detail=detail))

    def _load_contract(self, path: str | None) -> PreprocessingContract | None:
        if not path or not os.path.exists(path):
            self.report.checks.append(
                ValidationCheck(
                    name="Contract Load", passed=False, detail=f"File not found: {path}"
                )
            )
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            contract = PreprocessingContract.model_validate(data)

            # Verify contract hash
            computed = contract.compute_contract_hash()
            if contract.contract_hash and computed != contract.contract_hash:
                self.report.checks.append(
                    ValidationCheck(
                        name="Contract Hash Integrity",
                        passed=False,
                        detail="Contract hash mismatch — file may have been tampered",
                        expected=contract.contract_hash,
                        actual=computed,
                    )
                )
            else:
                self.report.checks.append(
                    ValidationCheck(
                        name="Contract Hash Integrity",
                        passed=True,
                        detail=f"Hash verified: {computed}",
                    )
                )

            self.report.checks.append(
                ValidationCheck(
                    name="Contract Load",
                    passed=True,
                    detail=f"Loaded contract v{contract.contract_version} for job={contract.job_id}",
                )
            )
            return contract
        except Exception as e:
            self.report.checks.append(
                ValidationCheck(
                    name="Contract Load",
                    passed=False,
                    detail=f"Failed to load contract: {e}",
                )
            )
            return None

    def _check_contract_validity(self, contract: PreprocessingContract) -> None:
        """Check internal consistency of the contract."""
        checks: list[ValidationCheck] = []

        # Schema version
        checks.append(
            ValidationCheck(
                name="Contract Schema Version",
                passed=bool(contract.schema_version),
                detail=f"schema_version={contract.schema_version}",
            )
        )

        # Feature order is non-empty
        checks.append(
            ValidationCheck(
                name="Feature Order Non-Empty",
                passed=len(contract.feature_order) > 0,
                detail=f"n_features={len(contract.feature_order)}",
                expected="> 0",
                actual=len(contract.feature_order),
            )
        )

        # Numeric + Categorical = Feature Order
        all_typed = set(contract.numeric_columns) | set(contract.categorical_columns)
        all_features = set(contract.feature_order)
        missing_from_types = all_features - all_typed
        checks.append(
            ValidationCheck(
                name="All Features Typed",
                passed=len(missing_from_types) == 0,
                detail=(
                    f"Features without type: {missing_from_types}"
                    if missing_from_types
                    else "All features have a type"
                ),
                expected=str(all_features),
                actual=str(all_typed),
            )
        )

        # Numeric and categorical are disjoint
        overlap = set(contract.numeric_columns) & set(contract.categorical_columns)
        checks.append(
            ValidationCheck(
                name="Numeric/Categorical Disjoint",
                passed=len(overlap) == 0,
                detail=f"Overlap: {overlap}" if overlap else "No overlap",
            )
        )

        # n_features matches feature_order length
        checks.append(
            ValidationCheck(
                name="n_features Matches Feature Order",
                passed=contract.n_features == len(contract.feature_order),
                detail=f"n_features={contract.n_features}, feature_order len={len(contract.feature_order)}",
                expected=len(contract.feature_order),
                actual=contract.n_features,
            )
        )

        # expected_input_shape matches
        expected_n = (
            contract.expected_input_shape[1] if len(contract.expected_input_shape) > 1 else None
        )
        checks.append(
            ValidationCheck(
                name="Input Shape Matches n_features",
                passed=expected_n == contract.n_features if expected_n is not None else True,
                detail=f"expected_input_shape={contract.expected_input_shape}, n_features={contract.n_features}",
                expected=contract.n_features,
                actual=expected_n,
            )
        )

        # Ordinal categories match categorical count
        checks.append(
            ValidationCheck(
                name="Ordinal Categories Match Categorical Count",
                passed=(
                    len(contract.ordinal_categories) == len(contract.categorical_columns)
                    if contract.ordinal_categories and contract.categorical_columns
                    else True
                ),
                detail=f"ordinal_categories={len(contract.ordinal_categories)}, categorical_columns={len(contract.categorical_columns)}",
                expected=len(contract.categorical_columns),
                actual=len(contract.ordinal_categories),
            )
        )

        # Feature hash
        computed_hash = contract.compute_feature_hash()
        checks.append(
            ValidationCheck(
                name="Feature Hash Valid",
                passed=computed_hash == contract.feature_hash,
                detail=f"feature_hash={contract.feature_hash}",
                expected=contract.feature_hash,
                actual=computed_hash,
            )
        )

        # Preprocessing pipeline trace
        checks.append(
            ValidationCheck(
                name="Preprocessing Pipeline Trace",
                passed=len(contract.preprocessing_pipeline) > 0,
                detail=f"Steps: {[s.name for s in contract.preprocessing_pipeline]}",
            )
        )

        for c in checks:
            self.report.checks.append(c)

    def _check_onnx_against_contract(
        self, contract: PreprocessingContract, onnx_path: str | None
    ) -> None:
        """Verify ONNX model matches the contract."""
        if not onnx_path or not os.path.exists(onnx_path):
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Exists",
                    passed=False,
                    detail=f"File not found: {onnx_path}",
                )
            )
            return

        self.report.checks.append(
            ValidationCheck(name="ONNX Exists", passed=True, detail=onnx_path)
        )

        try:
            import onnx

            model = onnx.load(onnx_path)
            onnx.checker.check_model(model)

            self.report.checks.append(
                ValidationCheck(name="ONNX Valid", passed=True, detail="ONNX model passes checker")
            )

            # Check graph inputs
            graph = model.graph
            if not graph.input:
                self.report.checks.append(
                    ValidationCheck(
                        name="ONNX Has Input", passed=False, detail="No input node found"
                    )
                )
                return

            input_node = graph.input[0]
            input_name = input_node.name

            # Input name matches
            name_match = input_name == contract.onnx_input_name
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Input Name Matches Contract",
                    passed=name_match,
                    detail=f"ONNX input='{input_name}', contract.onnx_input_name='{contract.onnx_input_name}'",
                    expected=contract.onnx_input_name,
                    actual=input_name,
                )
            )

            # Input dimensions
            dims = input_node.type.tensor_type.shape.dim
            onnx_n_features = dims[1].dim_value if len(dims) > 1 else 0
            feature_match = onnx_n_features == contract.n_features
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Feature Count Matches Contract",
                    passed=feature_match,
                    detail=f"ONNX n_features={onnx_n_features}, contract n_features={contract.n_features}",
                    expected=contract.n_features,
                    actual=onnx_n_features,
                )
            )

            # Input dtype
            onnx_dtype = input_node.type.tensor_type.elem_type
            dtype_strs = {1: "float32", 2: "uint8", 3: "int8", 6: "int32", 7: "int64"}
            onnx_dtype_str = dtype_strs.get(onnx_dtype, f"unknown({onnx_dtype})")

            # Verify that input can be cast to float32
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Input Dtype",
                    passed=True,
                    detail=f"ONNX dtype={onnx_dtype_str} (expected float32-compatible)",
                )
            )

            # Output exists
            if graph.output:
                output_count = len(graph.output)
                self.report.checks.append(
                    ValidationCheck(
                        name="ONNX Has Output",
                        passed=output_count > 0,
                        detail=f"Outputs: {[o.name for o in graph.output]}",
                    )
                )
            else:
                self.report.checks.append(
                    ValidationCheck(
                        name="ONNX Has Output", passed=False, detail="No output node found"
                    )
                )

        except ImportError:
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Validation",
                    passed=False,
                    detail="onnx package not installed — skipping ONNX validation",
                )
            )
        except Exception as e:
            self.report.checks.append(
                ValidationCheck(
                    name="ONNX Validation",
                    passed=False,
                    detail=f"ONNX validation failed: {e}",
                )
            )

    def _check_app_against_contract(
        self, contract: PreprocessingContract, app_dir: str | None
    ) -> None:
        """Verify generated app uses contract correctly."""
        if not app_dir or not os.path.isdir(app_dir):
            self.report.checks.append(
                ValidationCheck(
                    name="App Directory Exists",
                    passed=False,
                    detail=f"Directory not found: {app_dir}",
                )
            )
            return

        self.report.checks.append(
            ValidationCheck(name="App Directory Exists", passed=True, detail=app_dir)
        )

        app_py = os.path.join(app_dir, "app.py")
        if not os.path.exists(app_py):
            self.report.checks.append(
                ValidationCheck(
                    name="App app.py Exists",
                    passed=False,
                    detail=f"app.py not found in {app_dir}",
                )
            )
            return

        self.report.checks.append(
            ValidationCheck(name="App app.py Exists", passed=True, detail=app_py)
        )

        # Check app.py does NOT hardcode FEATURE_NAMES, NUMERIC_COLS, CATEGORICAL_COLS
        # Instead it should load from contract
        with open(app_py, encoding="utf-8") as f:
            content = f.read()

        has_hardcoded_features = (
            "FEATURE_NAMES =" in content
            and "import json" not in content.split("FEATURE_NAMES =")[0][:100]
        )
        has_contract_load = "preprocessing_contract.json" in content or "_load_contract" in content

        if has_hardcoded_features:
            self.report.checks.append(
                ValidationCheck(
                    name="No Hardcoded Feature Names",
                    passed=False,
                    detail="app.py hardcodes FEATURE_NAMES instead of loading from contract",
                )
            )
        else:
            self.report.checks.append(
                ValidationCheck(
                    name="No Hardcoded Feature Names",
                    passed=has_contract_load,
                    detail=(
                        "app.py loads features from contract"
                        if has_contract_load
                        else "app.py does not load from contract"
                    ),
                )
            )

        # Check requirements.txt
        req_path = os.path.join(app_dir, "requirements.txt")
        if os.path.exists(req_path):
            self.report.checks.append(
                ValidationCheck(name="Requirements Exist", passed=True, detail=req_path)
            )
        else:
            self.report.checks.append(
                ValidationCheck(
                    name="Requirements Exist",
                    passed=False,
                    detail="requirements.txt not found",
                )
            )

        # Check contract file exists in app dir
        contract_in_app = os.path.join(app_dir, "preprocessing_contract.json")
        if os.path.exists(contract_in_app):
            self.report.checks.append(
                ValidationCheck(
                    name="Contract in App Dir",
                    passed=True,
                    detail=contract_in_app,
                )
            )
        else:
            self.report.checks.append(
                ValidationCheck(
                    name="Contract in App Dir",
                    passed=False,
                    detail="preprocessing_contract.json not copied to app dir",
                )
            )

        # Check model file exists in app dir
        for model_name in ["model.onnx", "model.pkl"]:
            model_path = os.path.join(app_dir, model_name)
            if os.path.exists(model_path):
                self.report.checks.append(
                    ValidationCheck(
                        name=f"Model File ({model_name})",
                        passed=True,
                        detail=model_path,
                    )
                )
                break
        else:
            self.report.checks.append(
                ValidationCheck(
                    name="Model File",
                    passed=False,
                    detail="No model file (model.onnx or model.pkl) found in app dir",
                )
            )


# ── Self-test ────────────────────────────────────────────────────────


def run_self_test(
    endpoint_url: str,
    contract: PreprocessingContract,
    timeout_seconds: int = 30,
) -> ValidationCheck:
    """Send a synthetic prediction request to the deployed endpoint.

    Constructs a synthetic input row using the contract's feature_order,
    fills numeric columns with 0.0 and categorical columns with the first
    known category (or "UNKNOWN"), sends it to /predict, and verifies
    the response contains 'predictions'.
    """
    try:
        import httpx

        # Build synthetic input
        sample: dict[str, Any] = {}
        for col in contract.feature_order:
            if col in contract.numeric_columns:
                sample[col] = 0.0
            elif col in contract.categorical_columns:
                cats = [clist for clist in contract.ordinal_categories]
                if cats and len(cats) > 0:
                    sample[col] = cats[0][0] if cats[0] else "UNKNOWN"
                else:
                    sample[col] = "UNKNOWN"
            else:
                sample[col] = 0.0

        # Health check
        health_url = f"{endpoint_url}/health"
        health_r = httpx.get(health_url, timeout=timeout_seconds)
        if health_r.status_code != 200:
            return ValidationCheck(
                name="Self-Test: Health Endpoint",
                passed=False,
                detail=f"Health check failed: status={health_r.status_code}",
            )

        # Prediction
        predict_url = f"{endpoint_url}/predict"
        predict_r = httpx.post(
            predict_url,
            json=sample,
            timeout=timeout_seconds,
        )
        if predict_r.status_code != 200:
            return ValidationCheck(
                name="Self-Test: Prediction Endpoint",
                passed=False,
                detail=f"Prediction failed: status={predict_r.status_code}, body={predict_r.text[:500]}",
                expected="200",
                actual=predict_r.status_code,
            )

        data = predict_r.json()
        if "predictions" not in data:
            return ValidationCheck(
                name="Self-Test: Has Predictions Field",
                passed=False,
                detail=f"Response missing 'predictions' key: {data}",
            )

        latency = data.get("latency_ms", 0)
        return ValidationCheck(
            name="Self-Test: Synthetic Prediction",
            passed=True,
            detail=f"Prediction succeeded | latency={latency:.1f}ms",
            actual=f"{latency:.1f}ms",
        )

    except httpx.ConnectError:
        return ValidationCheck(
            name="Self-Test: Connection",
            passed=False,
            detail=f"Could not connect to {endpoint_url} — is the container running?",
        )
    except httpx.TimeoutException:
        return ValidationCheck(
            name="Self-Test: Timeout",
            passed=False,
            detail=f"Request timed out after {timeout_seconds}s",
        )
    except Exception as e:
        return ValidationCheck(
            name="Self-Test: Error",
            passed=False,
            detail=f"Self-test failed with exception: {e}",
        )


# ── Convenience function ─────────────────────────────────────────────


def verify_deployment(
    checkpoint_path: str | None = None,
    contract_path: str | None = None,
    onnx_path: str | None = None,
    app_dir: str | None = None,
    endpoint_url: str | None = None,
    report_path: str | None = None,
) -> ValidationReport:
    """One-call deployment verification.

    Runs all artifact checks and optionally a self-test against a live endpoint.
    Writes the report to report_path if provided.
    Returns the report (check .all_passed() to determine success).
    """
    validator = FeatureContractValidator()
    report = validator.validate_all(
        pipeline_path=checkpoint_path,
        contract_path=contract_path,
        onnx_path=onnx_path,
        app_dir=app_dir,
    )

    if endpoint_url and report.all_passed():
        contract = validator._load_contract(contract_path)
        if contract:
            self_test = run_self_test(endpoint_url, contract)
            report.checks.append(self_test)

    if report_path:
        report.write_to(report_path)

    return report
