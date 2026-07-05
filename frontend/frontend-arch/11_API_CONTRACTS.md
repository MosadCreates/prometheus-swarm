# Prometheus Swarm
# API Contracts

**Version:** 1.0.0

**Status:** Draft

**Owner:** Mohamed Mosad

**Last Updated:** July 2026

---

# Purpose

This document defines every public API exposed by Prometheus Swarm.

It specifies:

- REST endpoints
- WebSocket events
- Authentication
- Request format
- Response format
- Error handling
- Pagination
- File uploads
- Streaming
- Versioning

The API Contract serves as the agreement between frontend and backend implementations.

---

# API Principles

Every API must be:

- Predictable
- Versioned
- Secure
- Stateless (except WebSockets)
- Consistent
- Documented

---

# Base URL

```
/api/v1
```

Future versions:

```
/api/v2
```

No breaking changes inside the same API version.

---

# Authentication

Authentication uses JWT access tokens.

```
Authorization: Bearer <access_token>
```

Refresh tokens are stored securely and exchanged through dedicated authentication endpoints.

Protected routes require authentication.

---

# Standard Request Headers

```
Authorization

Content-Type

Accept

X-Request-ID
```

Optional

```
X-Workspace-ID
```

---

# Standard Response Format

Success

```json
{
  "success": true,
  "data": {},
  "meta": {},
  "message": null
}
```

Error

```json
{
  "success": false,
  "error": {
    "code": "MISSION_NOT_FOUND",
    "message": "Mission does not exist.",
    "details": {}
  }
}
```

Every endpoint follows this format.

---

# Authentication Endpoints

## Register

POST

```
/auth/register
```

Request

```json
{
  "name": "",
  "email": "",
  "password": ""
}
```

---

## Login

POST

```
/auth/login
```

Returns

```json
{
  "accessToken": "",
  "refreshToken": ""
}
```

---

## Refresh Token

POST

```
/auth/refresh
```

---

## Logout

POST

```
/auth/logout
```

---

## Current User

GET

```
/auth/me
```

---

# Project APIs

## List Projects

GET

```
/projects
```

---

## Create Project

POST

```
/projects
```

---

## Get Project

GET

```
/projects/{id}
```

---

## Update Project

PATCH

```
/projects/{id}
```

---

## Delete Project

DELETE

```
/projects/{id}
```

---

# Mission APIs

## Create Mission

POST

```
/missions
```

Example

```json
{
  "projectId": "",
  "objective": "",
  "attachments": []
}
```

Returns

```json
{
  "missionId": ""
}
```

---

## Get Mission

GET

```
/missions/{id}
```

---

## List Missions

GET

```
/missions
```

---

## Cancel Mission

POST

```
/missions/{id}/cancel
```

---

## Pause Mission

POST

```
/missions/{id}/pause
```

---

## Resume Mission

POST

```
/missions/{id}/resume
```

---

# Agent APIs

## List Agents

GET

```
/agents
```

---

## Agent Details

GET

```
/agents/{id}
```

---

## Agent Logs

GET

```
/agents/{id}/logs
```

---

## Agent Metrics

GET

```
/agents/{id}/metrics
```

---

# Artifact APIs

## List Artifacts

GET

```
/missions/{id}/artifacts
```

---

## Download Artifact

GET

```
/artifacts/{id}/download
```

---

## Preview Artifact

GET

```
/artifacts/{id}
```

---

# Dataset APIs

## Upload Dataset

POST

```
/datasets/upload
```

Multipart form upload.

---

## List Datasets

GET

```
/datasets
```

---

## Dataset Details

GET

```
/datasets/{id}
```

---

# Model APIs

## List Models

GET

```
/models
```

---

## Model Details

GET

```
/models/{id}
```

---

## Deploy Model

POST

```
/models/{id}/deploy
```

---

# Deployment APIs

## Deploy Mission

POST

```
/deployments
```

---

## Deployment Status

GET

```
/deployments/{id}
```

---

## Deployment Logs

GET

```
/deployments/{id}/logs
```

---

# Search API

GET

```
/search
```

Query Parameters

```
q
type
page
limit
```

Supports searching:

- Projects
- Missions
- Agents
- Models
- Artifacts
- Datasets

---

# File Upload

Uploads use:

```
multipart/form-data
```

Supported

- Images
- ZIP
- CSV
- JSON
- PDF
- Python Files
- Text Files

Large uploads should support chunked uploads in future versions.

---

# Pagination

Standard format

```json
{
  "data": [],
  "meta": {
    "page": 1,
    "limit": 20,
    "total": 145,
    "pages": 8
  }
}
```

---

# Filtering

Standard query parameters

```
status

createdAfter

createdBefore

sort

page

limit
```

---

# WebSocket

Mission updates are streamed through WebSockets.

Example endpoint

```
/ws
```

Clients authenticate using JWT.

---

# WebSocket Events

Mission Events

```
MISSION_CREATED

MISSION_STARTED

MISSION_PROGRESS

MISSION_COMPLETED

MISSION_FAILED
```

---

Agent Events

```
AGENT_ASSIGNED

AGENT_STARTED

AGENT_PROGRESS

AGENT_COMPLETED

AGENT_FAILED
```

---

Artifact Events

```
ARTIFACT_CREATED

ARTIFACT_UPDATED
```

---

Training Events

```
TRAINING_STARTED

TRAINING_PROGRESS

TRAINING_COMPLETED

TRAINING_FAILED
```

---

Deployment Events

```
DEPLOYMENT_STARTED

DEPLOYMENT_COMPLETED

DEPLOYMENT_FAILED
```

---

Notification Events

```
NOTIFICATION_CREATED
```

---

# WebSocket Payload

Example

```json
{
  "event": "AGENT_STARTED",
  "missionId": "mission_123",
  "agent": "Forge",
  "timestamp": "2026-07-04T14:31:15Z",
  "payload": {
    "objective": "Generate architecture"
  }
}
```

---

# Error Codes

Standardized codes

```
UNAUTHORIZED

FORBIDDEN

NOT_FOUND

VALIDATION_ERROR

MISSION_FAILED

AGENT_FAILED

UPLOAD_FAILED

DEPLOYMENT_FAILED

RATE_LIMITED

INTERNAL_SERVER_ERROR
```

Errors should remain stable across versions.

---

# Rate Limiting

Authenticated users

```
100 requests/minute
```

Mission execution endpoints may have stricter limits.

Rate limit responses include retry information.

---

# API Versioning

Breaking changes require a new version.

```
/api/v2
```

Minor additions should not break existing clients.

---

# Security

Requirements

- HTTPS only
- JWT authentication
- Input validation
- Output sanitization
- File scanning
- Rate limiting
- CSRF protection where applicable
- Secure headers

---

# Observability

Every request should include

```
requestId

userId

workspaceId

timestamp

duration
```

This enables traceability across distributed services.

---

# OpenAPI

Every REST endpoint must be documented using OpenAPI 3.1.

Generated documentation should include:

- Requests
- Responses
- Schemas
- Authentication
- Examples

The OpenAPI specification should remain synchronized with implementation.

---

# API Checklist

Before publishing a new endpoint:

- Authentication defined
- Validation implemented
- Error responses documented
- OpenAPI updated
- WebSocket events documented (if applicable)
- Tests written
- Rate limits reviewed
- Monitoring enabled

---

# Conclusion

The API Contract establishes a stable interface between the frontend, backend, orchestration layer, and future third-party integrations.

A consistent, versioned, and event-driven API ensures that Prometheus Swarm remains scalable, maintainable, and extensible as new agents, workflows, and capabilities are introduced.
