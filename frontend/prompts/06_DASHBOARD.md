# 05_DASHBOARD.md

# Prometheus Swarm Frontend — Dashboard

## Read First

Before starting, read:

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

Build the main Dashboard for Prometheus Swarm.

The Dashboard is the user's workspace home after authentication.

It should answer three questions immediately:

* What am I working on?
* What is currently happening?
* What should I do next?

Do not build backend functionality.

Use realistic mock data only.

---

# Scope

Frontend only.

Do not implement:

* Backend APIs
* Live WebSockets
* Authentication logic
* AI agent execution
* Model training
* Mission execution

Build only the interface and interactions.

---

# Dashboard Layout

The Dashboard should use the global App Shell.

The page consists of:

```text
Header

↓

Workspace Summary

↓

Quick Actions

↓

Recent Projects

↓

Active Missions

↓

Recent Activity

↓

Pinned Resources
```

The layout should feel spacious, organized, and focused.

---

# Page Header

Reuse the shared Page Header component.

Include:

* Welcome message
* Workspace name
* Current date
* Search shortcut
* Primary action button

Primary action:

"New Mission"

---

# Workspace Summary

Create a summary section with reusable Metric Cards.

Example metrics:

* Active Projects
* Running Missions
* Trained Models
* Available Datasets
* Recent Deployments

Use mock values.

Do not imply backend calculations.

---

# Quick Actions

Create a reusable action panel.

Examples:

* New Mission
* Create Project
* Upload Dataset
* View Models
* Open Training
* Open Deployments

Buttons should navigate to placeholder pages.

---

# Recent Projects

Create a reusable Project Card.

Each card should display:

* Project Name
* Description
* Last Updated
* Status Badge
* Mission Count
* Quick Actions

Use mock data.

Support:

* Hover effects
* Keyboard navigation

---

# Active Missions

Display currently active missions.

Each Mission Card should show:

* Mission Name
* Current Status
* Progress Indicator
* Assigned Agents (mock)
* Start Time
* Estimated Completion
* Open Mission button

Do not simulate execution.

---

# Recent Activity

Build an Activity Feed inspired by GitHub and Linear.

Activity examples:

* Mission created
* Dataset uploaded
* Model completed
* Deployment finished
* Project updated

Each item should include:

* Icon
* Title
* Description
* Relative timestamp

Use static mock data.

---

# Pinned Resources

Create a reusable section for frequently accessed items.

Examples:

* Favorite Projects
* Favorite Models
* Documentation
* Recent Artifacts

Allow placeholder pin/unpin interactions.

---

# Search Shortcut

Display a search entry point that integrates with the future Command Palette.

Example:

"Search projects, missions, models..."

No search functionality required.

---

# Empty States

Create elegant empty states for:

* No Projects
* No Missions
* No Activity
* No Resources

Each should include:

* Illustration placeholder
* Helpful message
* Primary action

---

# Loading States

Provide skeleton loaders for:

* Metric Cards
* Project Cards
* Mission Cards
* Activity Feed

Use reusable skeleton components.

---

# Responsive Behavior

Desktop:

* Multi-column layout

Laptop:

* Reduced spacing

Tablet:

* Single-column sections where appropriate

Maintain readability at all supported sizes.

---

# Motion

Implement subtle animations for:

* Card appearance
* Hover states
* Progress indicators
* Section loading
* Empty state transitions

Follow the Motion System.

Avoid excessive animation.

---

# Accessibility

Ensure:

* Keyboard navigation
* Screen reader compatibility
* Proper headings
* Semantic landmarks
* Focus indicators

All cards and actions should be accessible.

---

# Components to Build

Create reusable components:

* WorkspaceSummary
* MetricCard
* QuickActions
* ProjectCard
* MissionCard
* ActivityFeed
* ActivityItem
* ResourceCard
* EmptyWorkspace
* DashboardSection

These components should be reusable in future pages.

---

# Mock Data

Use static mock data stored in dedicated mock files.

Do not hardcode data inside components.

Examples include:

* Projects
* Missions
* Activity
* Metrics
* Resources

Structure mock data to resemble future API responses without assuming backend implementation.

---

# Visual Design

The Dashboard should communicate:

* Clarity
* Confidence
* Productivity
* Progress

Avoid unnecessary gradients or decorative graphics.

Whitespace and typography should do most of the visual work.

---

# Deliverables

Provide:

## Dashboard Sections

List all implemented sections.

---

## Components Created

List every reusable component.

---

## Mock Data Files

List created mock data sources.

---

## Files Created

List all new files.

---

## Files Modified

List all modified files.

---

## Notes

Mention reusable patterns and future extension points.

---

# Definition of Done

This task is complete only when:

* The Dashboard is fully implemented.
* All sections use reusable components.
* Mock data is separated from UI.
* Responsive layouts are complete.
* Theme support works.
* Accessibility requirements are met.
* Loading and empty states exist.
* Navigation actions route to placeholder pages where appropriate.
* No backend logic has been implemented.
* No undocumented APIs have been introduced.

Stop after completing the Dashboard.

Do not continue to Projects, Mission Composer, or any other feature automatically.
