# Prometheus Swarm
# Folder Structure

**Version:** 1.0.0

**Status:** Draft

**Owner:** Mohamed Mosad

**Last Updated:** July 2026

---

# Purpose

This document defines the official frontend directory structure for Prometheus Swarm.

The goals are:

- Scalability
- Clear ownership
- Feature isolation
- Reusability
- Maintainability
- Predictable organization

Every new file added to the project should follow this structure.

---

# Design Principles

The folder structure follows these principles:

- Feature-first organization
- Shared code only when truly reusable
- Business logic separated from UI
- Clear ownership
- Low coupling
- High cohesion

---

# High-Level Structure

```
frontend/

├── app/
├── features/
├── shared/
├── services/
├── stores/
├── providers/
├── hooks/
├── lib/
├── config/
├── types/
├── styles/
├── public/
├── tests/
├── scripts/
└── docs/
```

Each top-level directory has one responsibility.

---

# app/

Purpose

Next.js App Router.

Contains only:

- Routes
- Layouts
- Loading pages
- Error pages
- Metadata

Example

```
app/

    layout.tsx

    page.tsx

    login/

    register/

    dashboard/

    projects/

        [projectId]/

    missions/

        [missionId]/

    models/

    datasets/

    deployments/

    settings/
```

Business logic should never be placed here.

---

# features/

The heart of the application.

Each business domain owns its own feature.

```
features/

    authentication/

    dashboard/

    projects/

    missions/

    agents/

    artifacts/

    models/

    datasets/

    deployments/

    training/

    notifications/

    settings/

    search/
```

Each feature is self-contained.

---

# Standard Feature Layout

Every feature follows the same internal organization.

```
missions/

    api/

    components/

    hooks/

    services/

    stores/

    types/

    utils/

    constants/

    validators/

    mappers/

    tests/
```

Benefits

- Predictable
- Easy navigation
- Independent development

---

# shared/

Reusable resources.

```
shared/

    components/

    ui/

    icons/

    layouts/

    hooks/

    utils/

    constants/

    types/

    validators/

    animations/
```

Nothing inside `shared/` should depend on a specific feature.

---

# shared/ui/

Contains reusable UI primitives.

Examples

```
Button

Input

Card

Badge

Modal

Drawer

Tooltip

Table

Avatar

Tabs

Progress

Skeleton

Toast
```

These are the building blocks for all features.

---

# shared/components/

Higher-level reusable components.

Examples

```
MetricCard

PageHeader

SearchBar

StatusBadge

FileUploader

CommandPalette

CodeViewer

ActivityFeed
```

---

# services/

Application-wide services.

```
services/

    api/

    websocket/

    auth/

    analytics/

    logger/

    storage/

    uploader/

    notifications/
```

Services coordinate external systems.

---

# stores/

Global application state.

```
stores/

    auth.store.ts

    theme.store.ts

    workspace.store.ts

    notification.store.ts

    websocket.store.ts

    commandPalette.store.ts
```

Feature-specific state belongs inside the corresponding feature.

---

# providers/

Application providers.

```
providers/

    AuthProvider

    ThemeProvider

    QueryProvider

    SocketProvider

    MotionProvider

    NotificationProvider
```

These wrap the application at startup.

---

# hooks/

Global reusable hooks.

Examples

```
useDebounce

useClipboard

useKeyboardShortcut

useMediaQuery

useTheme

useWindowSize
```

Feature-specific hooks remain inside feature folders.

---

# lib/

Third-party library configuration.

```
lib/

    axios.ts

    queryClient.ts

    websocket.ts

    monaco.ts

    reactFlow.ts

    recharts.ts
```

Keeps initialization separate from business logic.

---

# config/

Application configuration.

```
config/

    env.ts

    routes.ts

    navigation.ts

    permissions.ts

    featureFlags.ts
```

No runtime business logic.

---

# types/

Global TypeScript types.

Examples

```
api.ts

common.ts

events.ts

pagination.ts

user.ts
```

Feature-specific types stay inside the feature.

---

# styles/

Global styling.

```
styles/

    globals.css

    themes.css

    tokens.css

    animations.css
```

Component styles should remain local whenever possible.

---

# public/

Static assets.

```
public/

    images/

    logos/

    icons/

    fonts/

    illustrations/
```

---

# tests/

Cross-feature tests.

```
tests/

    e2e/

    integration/

    fixtures/

    mocks/
```

Feature unit tests remain inside each feature.

---

# scripts/

Development scripts.

Examples

```
generate-types

lint

cleanup

seed-data

build-icons
```

---

# docs/

Frontend-specific documentation.

Examples

```
architecture

coding-standards

component-guidelines

performance
```

---

# Naming Conventions

Folders

```
kebab-case
```

Examples

```
mission-control

agent-details

training-dashboard
```

---

Files

```
PascalCase

Button.tsx

MissionCard.tsx

AgentDrawer.tsx
```

---

Hooks

```
useSomething.ts
```

Examples

```
useMission

useAgent

useTimeline

useArtifact
```

---

Stores

```
*.store.ts
```

Examples

```
mission.store.ts

theme.store.ts
```

---

Services

```
*.service.ts
```

Examples

```
mission.service.ts

upload.service.ts
```

---

Validators

```
*.schema.ts
```

Examples

```
mission.schema.ts

login.schema.ts
```

---

Constants

```
*.constants.ts
```

---

Utilities

```
*.utils.ts
```

---

# Import Rules

Preferred import order:

1. External libraries
2. Shared modules
3. Services
4. Feature modules
5. Relative imports

Avoid deeply nested relative imports.

Prefer configured path aliases.

Example

```
@/features/missions
@/shared/components
@/services/api
@/stores
```

---

# Dependency Rules

Allowed

```
Feature
    ↓
Shared

Feature
    ↓
Services

Feature
    ↓
API
```

Not Allowed

```
Feature A

↓

Feature B

↓

Feature A
```

Avoid circular dependencies.

---

# Ownership Rules

Every file should have one clear owner.

Shared code requires careful review before modification.

Features should evolve independently.

---

# Growth Strategy

As Prometheus Swarm grows:

- Add new features under `features/`
- Add reusable utilities under `shared/`
- Avoid creating new top-level folders unless absolutely necessary

The structure should remain stable as the application scales.

---

# Example Project Tree

```
frontend/

├── app/
├── features/
│   ├── authentication/
│   ├── dashboard/
│   ├── projects/
│   ├── missions/
│   ├── agents/
│   ├── artifacts/
│   ├── models/
│   ├── datasets/
│   ├── deployments/
│   ├── training/
│   ├── notifications/
│   └── settings/
├── shared/
├── services/
├── stores/
├── providers/
├── hooks/
├── lib/
├── config/
├── types/
├── styles/
├── public/
├── tests/
├── scripts/
└── docs/
```

---

# Folder Checklist

Before creating a new folder, ask:

- Does this belong to an existing feature?
- Is it reusable?
- Is it application-wide?
- Does it introduce unnecessary complexity?
- Can it live inside an existing module?

Prefer extending the existing structure over creating new top-level directories.

---

# Conclusion

The Prometheus Swarm folder structure is designed to support a large-scale, modular frontend codebase.

By organizing code around features, separating reusable resources, and enforcing consistent naming and dependency rules, the project remains maintainable, scalable, and approachable for both human developers and AI coding agents.
