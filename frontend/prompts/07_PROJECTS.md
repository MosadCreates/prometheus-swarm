# 07_PROJECTS.md

# Prometheus Swarm Frontend — Projects

## Read First

Before beginning, read:

* 00_MASTER_PROMPT.md
* 01_PRODUCT_VISION.md
* 02_DESIGN_PRINCIPLES.md
* 03_INFORMATION_ARCHITECTURE.md
* 04_USER_FLOWS.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 12_FRONTEND_ARCHITECTURE.md

Follow these documents exactly.

---

# Objective

Build the complete Project Management experience for Prometheus Swarm.

A Project is the primary workspace where users design, build, train, evaluate, and deploy AI systems.

The interface should make projects feel like living engineering workspaces rather than simple folders.

---

# Scope

Frontend only.

Do NOT implement:

* Backend APIs
* Database logic
* AI execution
* Agent orchestration
* Deployment logic
* Authentication logic

Use structured mock data only.

---

# Pages to Build

Create the following pages:

```text
/projects

/projects/new

/projects/[projectId]

/projects/[projectId]/settings
```

No backend integration.

---

# User Journey

```
Dashboard
      ↓
Projects
      ↓
Create Project
      ↓
Project Overview
      ↓
Create Mission
```

Projects are the entry point for all engineering work.

---

# Projects List Page

Display all user projects.

Include:

* Search
* Filters
* Sort
* Grid/List toggle
* New Project button

Support:

* Empty state
* Loading state
* Error state (mock)

---

# Search

Allow searching by:

* Project Name
* Description
* Tags

UI only.

No backend search.

---

# Filters

Support mock filtering by:

* Status
* Last Updated
* Favorites
* Tags

Use local state only.

---

# Sorting

Provide options:

* Recently Updated
* Alphabetical
* Date Created
* Most Active

---

# Project Card

Create a reusable ProjectCard component.

Each card displays:

* Project Name
* Description
* Status Badge
* Tags
* Last Updated
* Mission Count
* Dataset Count
* Model Count
* Deployment Status
* Favorite Button

Hover actions:

* Open
* Duplicate (UI only)
* Archive (UI only)

---

# Create Project

Build a dedicated project creation page.

Fields:

* Project Name
* Description
* Category
* Tags
* Color/Icon
* Visibility (UI only)

Validation:

* Required fields
* Character limits
* Duplicate name warning (mock)

After creation:

Navigate to the Project Overview page using mock data.

---

# Project Overview

This is the project's home.

Layout:

```text
Project Header

↓

Overview Cards

↓

Recent Missions

↓

Datasets

↓

Models

↓

Artifacts

↓

Recent Activity
```

---

# Project Header

Display:

* Project Name
* Description
* Status
* Tags
* Last Updated
* Favorite Toggle

Actions:

* New Mission
* Upload Dataset
* Project Settings

No backend actions.

---

# Overview Cards

Create reusable MetricCards.

Examples:

* Missions
* Models
* Datasets
* Deployments
* Artifacts

Mock values only.

---

# Recent Missions

Display mission cards.

Each card:

* Name
* Status
* Progress
* Created
* Open button

Mock data only.

---

# Datasets Section

Display reusable DatasetCards.

Information:

* Name
* Size
* Type
* Updated

Placeholder actions:

* View
* Remove

---

# Models Section

Display reusable ModelCards.

Information:

* Name
* Version
* Status
* Accuracy (mock)
* Updated

---

# Artifacts Section

Display reusable ArtifactCards.

Examples:

* Code
* Reports
* Documentation
* Training Logs

Support preview placeholders.

---

# Recent Activity

Create an activity timeline.

Examples:

* Mission Created
* Dataset Uploaded
* Model Generated
* Artifact Exported

Use static mock data.

---

# Project Settings

Create a settings page.

Sections:

* General
* Appearance
* Tags
* Archive
* Delete Project (UI only)

No destructive backend operations.

---

# Empty States

Provide dedicated empty states for:

* No Projects
* No Missions
* No Models
* No Datasets
* No Artifacts

Each should include:

* Helpful explanation
* Primary action
* Secondary action

---

# Loading States

Create skeletons for:

* Project Cards
* Overview Cards
* Lists
* Timeline

Use shared Skeleton components.

---

# Components to Build

Create reusable components:

* ProjectCard
* ProjectHeader
* ProjectMetrics
* ProjectOverview
* DatasetCard
* ModelCard
* ArtifactCard
* ProjectTimeline
* Tag
* FavoriteButton
* ProjectStatusBadge
* ProjectGrid
* ProjectList

These components should be reusable throughout the application.

---

# Mock Data

Store all mock data in dedicated files.

Examples:

* Projects
* Missions
* Models
* Datasets
* Artifacts
* Activity

Never hardcode mock data inside components.

---

# Motion

Implement:

* Card hover effects
* Page transitions
* List appearance
* Expand/collapse interactions
* Button feedback

Follow the Motion System.

Animations should reinforce clarity, not decoration.

---

# Accessibility

Ensure:

* Keyboard navigation
* Screen reader compatibility
* Proper headings
* Focus management
* Semantic HTML

All interactive elements must be accessible.

---

# Responsive Design

Desktop:

* Multi-column layout

Laptop:

* Adaptive grid

Tablet:

* Single-column content

Maintain a consistent and readable experience.

---

# Visual Style

Projects should feel:

* Organized
* Professional
* Calm
* Engineering-focused

Use whitespace, hierarchy, and typography to communicate structure.

---

# Deliverables

Provide:

## Pages Created

List all project pages.

---

## Components Created

List all reusable project components.

---

## Mock Data Files

List all mock data sources.

---

## Files Created

List every new file.

---

## Files Modified

List modified files.

---

## Notes

Highlight reusable patterns, assumptions, and future integration points.

---

# Definition of Done

This task is complete only when:

* Projects list page is complete.
* Create Project page is complete.
* Project Overview page is complete.
* Project Settings page is complete.
* Reusable components have been created.
* Mock data is separated from UI.
* Responsive layouts work.
* Accessibility requirements are met.
* Theme support works.
* No backend functionality has been implemented.
* No undocumented APIs have been introduced.

Stop after completing the Projects feature.

Do not proceed to Mission Composer or any other feature automatically.
