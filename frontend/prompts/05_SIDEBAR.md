# 05_SIDEBAR.md

# Prometheus Swarm Frontend — Sidebar Navigation

## Read First

Before beginning, read:

* 00_MASTER_PROMPT.md
* 02_DESIGN_PRINCIPLES.md
* 03_INFORMATION_ARCHITECTURE.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 12_FRONTEND_ARCHITECTURE.md

Follow these documents exactly.

---

# Objective

Build the complete application sidebar for Prometheus Swarm.

The sidebar is the primary navigation component and should provide users with a clear overview of their workspace, projects, and recent activity.

It should feel calm, premium, and highly usable.

---

# Scope

Frontend only.

Do NOT implement:

* Backend APIs
* Authentication logic
* Real-time updates
* Business logic

Use mock data where necessary.

---

# Design Inspiration

Take inspiration from:

* Claude
* Cursor
* Linear
* GitHub
* Vercel

Do NOT copy their UI.

Create a unique Prometheus Swarm experience.

---

# Sidebar Layout

Structure:

```text
┌────────────────────────────┐
│ Logo                       │
│ Workspace Switcher          │
├────────────────────────────┤
│ Search / Command Palette    │
├────────────────────────────┤
│ Navigation                  │
├────────────────────────────┤
│ Recent Missions             │
├────────────────────────────┤
│ Recent Projects             │
├────────────────────────────┤
│ Models Built               │
├────────────────────────────┤
│ Storage Usage (optional)    │
├────────────────────────────┤
│ User Profile               │
└────────────────────────────┘
```

---

# Logo Area

Display:

* Prometheus Swarm logo
* Product name

Clicking the logo returns to the Dashboard.

---

# Workspace Switcher

Create a workspace selector UI.

Display:

* Current workspace
* Dropdown icon

Use mock workspaces.

Do not implement switching logic.

---

# Search

Place a command/search entry near the top.

Placeholder:

```
Search...

⌘K
```

Clicking should open the Command Palette UI.

No search functionality.

---

# Navigation

Include primary navigation items:

* Dashboard
* Projects
* Missions
* Models
* Datasets
* Training
* Deployments
* Settings

Each item should include:

* Icon
* Label
* Active state
* Hover state
* Focus state

Support nested groups for future expansion.

---

# Recent Missions

Display a scrollable list of recent missions.

Each item includes:

* Mission name
* Status indicator
* Timestamp

Clicking opens the placeholder Mission page.

Use mock data.

---

# Recent Projects

Display recently accessed projects.

Each item includes:

* Project name
* Color indicator
* Last opened time

Support hover effects.

---

# Models Built

Show a compact list of recently created models.

Each item includes:

* Model name
* Status badge

Use mock data only.

---

# Storage Widget (Optional)

Display a small usage card showing:

* Storage used
* Storage available
* Progress bar

Static values only.

---

# User Section

Place at the bottom.

Display:

* Avatar
* User name
* Email
* Expand icon

Dropdown contains:

* Profile
* Preferences
* Documentation
* Theme
* Logout (UI only)

---

# Sidebar States

Support:

* Expanded
* Collapsed
* Hover-expanded (optional)
* Tablet overlay

Transitions should be smooth.

---

# Collapse Behavior

Collapsed mode should display:

* Icons only
* Tooltips on hover

Remember the user's preference locally.

No backend persistence.

---

# Navigation Behavior

Support:

* Active route highlighting
* Hover animations
* Keyboard navigation
* Focus management

Nested sections should be collapsible.

---

# Empty States

If there are no recent projects or missions:

Display an elegant empty state encouraging users to create their first project or mission.

---

# Loading States

Create skeletons for:

* Navigation
* Projects
* Missions
* User profile

Reuse existing Skeleton components.

---

# Motion

Implement:

* Sidebar collapse animation
* Navigation hover effects
* Active indicator transition
* Dropdown animation
* Tooltip animation

Follow the Motion System.

Avoid excessive movement.

---

# Accessibility

Ensure:

* Keyboard navigation
* ARIA labels
* Screen reader compatibility
* Focus visibility
* Semantic navigation landmarks

The sidebar should be fully usable without a mouse.

---

# Responsive Design

Desktop

* Persistent sidebar

Laptop

* Collapsible sidebar

Tablet

* Overlay drawer

Smooth transitions between layouts.

---

# Components to Build

Create reusable components:

* Sidebar
* SidebarHeader
* WorkspaceSwitcher
* SidebarSearch
* SidebarNav
* SidebarNavItem
* SidebarSection
* RecentMissionItem
* RecentProjectItem
* ModelItem
* StorageCard
* UserProfileCard
* SidebarFooter

Do not duplicate layout code.

---

# Mock Data

Store all mock data separately.

Examples:

* Navigation items
* Workspaces
* Projects
* Missions
* Models
* User profile

Do not hardcode data inside components.

---

# Visual Quality

The sidebar should communicate:

* Organization
* Focus
* Professionalism
* Trust

Spacing and typography should provide clarity without visual clutter.

---

# Deliverables

Provide:

## Components Created

List every reusable sidebar component.

---

## Sidebar Features

Summarize implemented behaviors.

---

## Mock Data Files

List all created mock data sources.

---

## Files Created

List all new files.

---

## Files Modified

List all modified files.

---

## Notes

Highlight reusable patterns and future integration points.

---

# Definition of Done

This task is complete only when:

* Sidebar is fully implemented.
* Expanded and collapsed modes work.
* Navigation is reusable.
* Recent sections display mock data.
* User menu is complete.
* Theme support works.
* Responsive behavior is complete.
* Accessibility requirements are met.
* Mock data is separated from UI.
* No backend functionality has been implemented.

Stop after completing the Sidebar.

Do not continue to the Dashboard or any other feature automatically.
