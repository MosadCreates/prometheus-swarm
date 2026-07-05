# 03_APP_SHELL_LAYOUT.md

# Prometheus Swarm Frontend — Application Shell

## Read First

Before starting this task, read:

* 00_MASTER_PROMPT.md
* 02_DESIGN_PRINCIPLES.md
* 03_INFORMATION_ARCHITECTURE.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 12_FRONTEND_ARCHITECTURE.md
* 13_FOLDER_STRUCTURE.md

These documents define the application's architecture and design language.

---

# Objective

Build the global application shell used throughout Prometheus Swarm.

This task establishes the reusable layout that every authenticated page will use.

Do **NOT** build feature pages or business logic.

---

# Scope

Frontend only.

Do not implement:

* Authentication
* Dashboard
* Projects
* Mission Composer
* Mission Control
* Agent pages
* API requests
* Backend integration

Build only the reusable application frame.

---

# Inspiration

The application shell should feel inspired by:

* Claude
* Cursor
* Linear
* GitHub
* Vercel

The result must be an original design consistent with Prometheus Swarm.

---

# Primary Layout

Create the following structure:

```
┌────────────────────────────────────────────────────┐
│ Header                                             │
├───────────────┬────────────────────────────────────┤
│               │                                    │
│               │                                    │
│ Sidebar       │ Main Content                       │
│               │                                    │
│               │                                    │
├───────────────┴────────────────────────────────────┤
│ Optional Status / Footer                           │
└────────────────────────────────────────────────────┘
```

The layout should be responsive and reusable.

---

# Sidebar

Create a collapsible sidebar.

The sidebar should support:

* Expanded mode
* Collapsed icon-only mode
* Smooth animation
* Keyboard navigation

Include placeholder navigation items for:

* Dashboard
* Projects
* Missions
* Models
* Datasets
* Training
* Deployments
* Settings

Do not connect them to real pages yet.

---

# Header

Build a reusable top header.

Include placeholders for:

* Workspace title
* Search button
* Command palette shortcut
* Notifications
* Theme switch
* User avatar
* User menu

No backend functionality.

---

# Main Content Area

Create a reusable content container.

Requirements:

* Consistent spacing
* Maximum width support
* Responsive layout
* Scroll handling
* Empty content placeholder

Future pages will render inside this area.

---

# Command Palette

Build only the UI.

Include:

* Search input
* Recent actions section
* Navigation results
* Keyboard shortcut hint

No search logic.

No backend integration.

---

# Notification Center

Create the UI for a notification panel.

Support:

* Empty state
* Notification item
* Read/unread styles
* Timestamp
* Scrollable list

Use mock data only.

---

# User Menu

Create a dropdown menu with placeholder actions:

* Profile
* Preferences
* Theme
* Documentation
* Sign Out

No authentication logic.

---

# Theme Switcher

Implement:

* Light mode
* Dark mode
* Smooth transition
* System preference support

Use the design system created previously.

---

# Breadcrumbs

Create a reusable breadcrumb component.

Support:

* Multiple levels
* Icons
* Truncation
* Overflow handling

Use placeholder data.

---

# Page Header Component

Create a reusable page header.

Support:

* Title
* Subtitle
* Actions
* Status badges
* Breadcrumbs

Future pages should reuse this component.

---

# Navigation

Navigation should support:

* Active item
* Hover state
* Focus state
* Disabled state
* Nested groups (placeholder only)
* Collapsible sections

---

# Empty State

Design an elegant empty workspace state.

Include:

* Illustration placeholder
* Title
* Description
* Primary action
* Secondary action

This component should be reusable across the application.

---

# Loading States

Create layout skeletons for:

* Sidebar
* Header
* Content
* Lists
* Cards

Follow the design system.

---

# Responsive Behavior

Desktop

* Full sidebar

Laptop

* Collapsible sidebar

Tablet

* Overlay sidebar

Transitions should be smooth and maintain context.

---

# Motion

Apply animations defined in the Motion System.

Include:

* Sidebar collapse
* Drawer transitions
* Dropdown menus
* Theme transition
* Hover interactions

Animations should communicate state changes, not decorate the interface.

---

# Accessibility

Ensure:

* Keyboard navigation
* Focus management
* Semantic landmarks
* ARIA labels where appropriate
* Screen reader compatibility

Accessibility is required.

---

# Code Quality

All components should:

* Be reusable
* Be fully typed
* Avoid duplicated logic
* Follow the folder structure
* Use composition over duplication

---

# Mock Data

You may use static mock data only for:

* Navigation items
* Notifications
* Breadcrumbs
* User information

Do not simulate backend behavior.

---

# Deliverables

Provide:

## Components Created

List every reusable component.

---

## Layout Structure

Explain the application shell.

---

## Files Created

List all created files.

---

## Files Modified

List modified files.

---

## Reusable Patterns

Describe any reusable layout patterns introduced.

---

## Notes

Mention assumptions and future extension points.

---

# Definition of Done

This task is complete only when:

* The application shell is fully implemented.
* Sidebar works in expanded and collapsed modes.
* Header is complete.
* Theme switching functions.
* Navigation components are reusable.
* Command palette UI exists.
* Notification panel UI exists.
* User menu UI exists.
* Responsive layout is complete.
* Accessibility requirements are met.
* No feature pages have been built.
* No backend logic has been added.

Stop after completing the application shell.

Do not proceed to authentication or any other feature automatically.
