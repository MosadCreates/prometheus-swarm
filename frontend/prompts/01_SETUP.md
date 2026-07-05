# 01_SETUP.md

# Prometheus Swarm Frontend — Project Foundation

## Your Role

You are a Senior Frontend Architect and Staff React Engineer responsible for creating the entire frontend foundation for Prometheus Swarm.

You are **NOT** building features.

You are **ONLY** creating a production-grade frontend foundation that future implementation prompts will build upon.

Think like an engineer preparing a codebase that will grow to hundreds of components and thousands of files.

---

# IMPORTANT

Read and follow these documents before making any changes.

Required reading:

```
docs/frontend/

01_PRODUCT_VISION.md
02_DESIGN_PRINCIPLES.md
03_INFORMATION_ARCHITECTURE.md
04_USER_FLOWS.md
05_PAGE_SPECIFICATIONS.md
06_COMPONENT_LIBRARY.md
07_DESIGN_SYSTEM.md
08_MOTION_SYSTEM.md
11_API_CONTRACTS.md
12_FRONTEND_ARCHITECTURE.md
13_FOLDER_STRUCTURE.md
14_IMPLEMENTATION_ROADMAP.md
```

These documents are the single source of truth.

Never contradict them.

---

# Scope

Frontend only.

Do NOT touch:

* backend
* API implementation
* database
* AI agents
* orchestration
* authentication backend
* model logic
* deployment logic
* Python
* infrastructure

If backend functionality is required, assume it already exists.

---

# Objective

Initialize the frontend project and prepare a scalable architecture.

When finished, the project should be ready to begin implementing features without any structural changes.

No pages.

No business logic.

No feature implementation.

Only the foundation.

---

# Technology Stack

Create the project using:

* Next.js (App Router)
* React
* TypeScript
* Tailwind CSS
* shadcn/ui
* Framer Motion
* Zustand
* TanStack Query
* React Hook Form
* Zod
* Lucide React
* React Flow
* Monaco Editor
* Sonner
* clsx
* tailwind-merge

Use the latest stable versions.

---

# Project Structure

Create the folder structure defined in:

```
13_FOLDER_STRUCTURE.md
```

Do not invent your own architecture.

---

# Configure

Configure the project with:

* TypeScript
* ESLint
* Prettier
* Path aliases
* Absolute imports
* Environment variables
* Git ignore
* EditorConfig
* VS Code recommendations
* Husky
* lint-staged

Everything should work immediately after cloning.

---

# Install Dependencies

Install all libraries required for future implementation.

Do not wait until later prompts.

---

# Tailwind

Configure:

* Tailwind
* PostCSS
* Global styles
* CSS variables

Do not build the design system yet.

Only prepare the infrastructure.

---

# shadcn/ui

Initialize shadcn.

Do NOT generate every component.

Only configure the library correctly.

---

# Theme

Prepare:

* Light mode
* Dark mode

No custom colors yet.

---

# Routing

Create empty routes only.

Example:

```
/

login

register

dashboard

projects

missions

models

datasets

deployments

settings
```

Each page may temporarily render a placeholder.

No feature implementation.

---

# Providers

Create the application providers.

Examples:

* Theme Provider
* Query Provider
* Notification Provider

Only wiring.

No business logic.

---

# Global Layout

Create the root layout.

Include placeholders for:

* Sidebar
* Header
* Main Content

Do not implement them.

---

# Assets

Create folders for:

```
public/

images/

icons/

logos/

illustrations/

fonts/
```

---

# Configuration Files

Prepare:

```
.env.example

README.md

.prettierrc

.eslintrc

.editorconfig

tsconfig.json
```

Update configurations where necessary.

---

# Scripts

Ensure package scripts exist for:

* dev
* build
* start
* lint
* format
* typecheck

---

# Code Quality

The project must:

* compile successfully
* have zero TypeScript errors
* have zero ESLint errors
* have zero console warnings

---

# Performance

Enable:

* Strict Mode
* App Router
* Code splitting where applicable
* Dynamic imports support

---

# Accessibility

Prepare the project to support:

* keyboard navigation
* screen readers
* reduced motion

Do not implement features yet.

---

# Responsiveness

Prepare breakpoints only.

No responsive layouts yet.

---

# Documentation

If configuration differs from the documentation, update the documentation accordingly.

Never ignore inconsistencies.

---

# Deliverables

At the end, provide a summary including:

## Files Created

List every created file.

---

## Dependencies Installed

List every installed package.

---

## Configuration Completed

Summarize every configuration step.

---

## Remaining Work

List what future prompts will implement.

---

# Constraints

You MUST NOT:

* build pages
* build components
* build the sidebar
* build authentication
* build dashboard
* build Mission Control
* build Agent UI
* create mock APIs
* create backend code
* modify backend files

Stay strictly within project initialization.

---

# Definition of Done

This prompt is complete only if:

* The project starts successfully.
* All dependencies are installed.
* The architecture matches the documentation.
* Folder structure is complete.
* Configuration is production-ready.
* No features have been implemented.
* The project is ready for Prompt 02.

Stop immediately after completing the setup.

Do not continue to Prompt 02 automatically.
