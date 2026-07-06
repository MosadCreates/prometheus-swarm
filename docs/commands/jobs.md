# Jobs Commands

## `job cancel`
Cancel a running job.
- **Category:** Jobs
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus job cancel <job_id>`
- **Related:** `job status`, `job list`

## `job delete`
Delete a job record.
- **Category:** Jobs
- **Tier:** 3
- **Implemented:** ✗
- **Since:** v0.2.0

## `job list`
List all jobs.
- **Category:** Jobs
- **Tier:** 1
- **Implemented:** ✓
- **Aliases:** `job ls`
- **Examples:**
  - `prometheus prometheus job list`
- **Related:** `job status`

## `job logs`
Show job execution logs.
- **Category:** Jobs
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus job logs <job_id>`
- **Related:** `job status`, `job list`

## `job retry`
Retry a failed job.
- **Category:** Jobs
- **Tier:** 2
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus job retry <job_id>`
- **Related:** `job status`, `job list`

## `job status`
Show job status.
- **Category:** Jobs
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus job status <job_id>`
- **Related:** `job list`, `job submit`

## `job submit`
Submit a dataset to the pipeline.
- **Category:** Jobs
- **Tier:** 1
- **Implemented:** ✓
- **Examples:**
  - `prometheus prometheus job submit data.csv -d 'classify' -t target`
- **Related:** `job status`, `job list`
- **Requires workspace:** yes
- **Requires provider:** yes
