"""All Prometheus metrics. The ONLY place metric objects are created."""
from prometheus_client import Counter, Gauge, Histogram

furnace_epochs_total = Counter(
    "prometheus_furnace_epochs_total", "Total training epochs", ["job_id", "model_type"])
furnace_train_loss = Gauge(
    "prometheus_furnace_train_loss", "Current training loss", ["job_id"])
furnace_val_loss = Gauge(
    "prometheus_furnace_val_loss", "Current validation loss", ["job_id"])
furnace_crashes_total = Counter(
    "prometheus_furnace_crashes_total", "Total crashes", ["job_id", "exception_type"])
furnace_training_duration_seconds = Histogram(
    "prometheus_furnace_training_duration_seconds", "Training duration",
    ["job_id", "model_type"], buckets=[60,300,600,1200,1800,3600])
dissect_patches_attempted_total = Counter(
    "prometheus_dissect_patches_attempted_total", "Patch attempts",
    ["error_category", "attempt_number"])
dissect_patches_successful_total = Counter(
    "prometheus_dissect_patches_successful_total", "Successful patches", ["error_category"])
dissect_patches_escalated_total = Counter(
    "prometheus_dissect_patches_escalated_total", "Escalated jobs", [])
dissect_patch_confidence = Histogram(
    "prometheus_dissect_patch_confidence", "Patch confidence",
    ["error_category"], buckets=[.1,.2,.3,.4,.5,.6,.7,.8,.9,1.0])
dissect_patch_duration_seconds = Histogram(
    "prometheus_dissect_patch_duration_seconds", "Time to patch",
    [], buckets=[1,5,10,30,60,120])
arbiter_decisions_total = Counter(
    "prometheus_arbiter_decisions_total", "Evaluation decisions", ["decision"])
arbiter_primary_metric_value = Gauge(
    "prometheus_arbiter_primary_metric_value", "Primary metric", ["job_id", "metric_name"])
harbor_prediction_requests_total = Counter(
    "prometheus_harbor_prediction_requests_total", "Prediction requests",
    ["job_id", "status_code"])
harbor_prediction_latency_seconds = Histogram(
    "prometheus_harbor_prediction_latency_seconds", "Prediction latency",
    ["job_id"], buckets=[.001,.005,.01,.025,.05,.1,.25,.5,1.0])
harbor_psi_score = Gauge(
    "prometheus_harbor_psi_score", "Current PSI score", ["job_id"])
harbor_drift_alerts_total = Counter(
    "prometheus_harbor_drift_alerts_total", "Drift alerts", ["job_id"])
orchestrator_jobs_submitted_total = Counter(
    "prometheus_orchestrator_jobs_submitted_total", "Jobs submitted", [])
orchestrator_jobs_completed_total = Counter(
    "prometheus_orchestrator_jobs_completed_total", "Jobs completed", [])
orchestrator_jobs_failed_total = Counter(
    "prometheus_orchestrator_jobs_failed_total", "Jobs failed", ["source_agent"])
orchestrator_job_e2e_duration_seconds = Histogram(
    "prometheus_orchestrator_job_e2e_duration_seconds", "E2E job duration",
    [], buckets=[60,300,600,900,1200,1800,3600])
