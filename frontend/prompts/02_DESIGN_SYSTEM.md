# 02_DESIGN_SYSTEM.md

# Prometheus Swarm Frontend — Design System

## Read First

Before beginning, read and follow:

* 00_MASTER_PROMPT.md
* 07_DESIGN_SYSTEM.md
* 06_COMPONENT_LIBRARY.md
* 08_MOTION_SYSTEM.md
* 13_FOLDER_STRUCTURE.md

These documents are the source of truth.

---

# Objective

Build the complete reusable Design System for Prometheus Swarm.

Do **NOT** build any application pages.

Do **NOT** build business features.

Only create reusable UI primitives, tokens, layouts, and shared components that every future feature will use.

This prompt should establish the visual and interaction foundation of the application.

---

# Scope

Frontend only.

Do not:

* Create backend logic
* Create authentication
* Build the dashboard
* Build Mission Control
* Build Projects
* Build Agent pages
* Build API calls

Only the design system.

---

# Primary Goal

After completing this task, developers should be able to build any screen in the application using reusable components from the design system without creating new foundational UI elements.

---

# Build Design Tokens

Implement centralized design tokens for:

## Colors

Create semantic tokens instead of hardcoded values.

Examples:

* Background
* Surface
* Surface Elevated
* Border
* Primary
* Secondary
* Success
* Warning
* Danger
* Info
* Accent
* Text Primary
* Text Secondary
* Muted
* Disabled

Support:

* Light Theme
* Dark Theme

Never hardcode colors inside components.

---

## Typography

Create a typography scale.

Include:

* Display
* H1
* H2
* H3
* H4
* Body Large
* Body
* Body Small
* Caption
* Label
* Code

Use consistent font weights and line heights.

---

## Spacing

Create spacing tokens.

Examples:

* xs
* sm
* md
* lg
* xl
* 2xl
* 3xl

Never use arbitrary spacing values unless absolutely necessary.

---

## Border Radius

Create reusable radius tokens.

Examples:

* Small
* Medium
* Large
* Full

---

## Shadows

Create shadow tokens for:

* Card
* Floating Panel
* Modal
* Drawer
* Dropdown

---

## Animation Tokens

Define reusable durations and easing values.

Examples:

* Fast
* Normal
* Slow

Follow the Motion System documentation.

---

# Theme System

Implement:

* Light Mode
* Dark Mode
* Theme persistence
* System preference detection

The theme should apply globally.

---

# Shared UI Components

Create reusable UI primitives.

Examples include:

* Button
* IconButton
* Input
* Textarea
* Select
* Checkbox
* Radio Group
* Switch
* Slider
* Badge
* Chip
* Avatar
* Tooltip
* Card
* Divider
* Tabs
* Accordion
* Dialog
* Drawer
* Popover
* Dropdown Menu
* Toast
* Progress
* Spinner
* Skeleton
* Scroll Area

Every component should:

* Support light and dark themes
* Be accessible
* Be keyboard navigable
* Follow the design tokens
* Be reusable

---

# Layout Components

Create reusable layout primitives.

Examples:

* AppShell
* Container
* Stack
* Grid
* Section
* Sidebar Container
* Top Navigation Container
* Page Header
* Empty State
* Error State
* Loading State

Do not implement feature-specific layouts.

---

# Feedback Components

Create components for:

* Success messages
* Error alerts
* Warning alerts
* Informational alerts
* Confirmation dialogs
* Loading indicators

---

# Data Display Components

Create reusable components such as:

* Table
* Metric Card
* Stat Card
* Status Badge
* Timeline Item
* Activity Row
* Key/Value Display

Do not connect them to real data.

Use mock examples only.

---

# Navigation Components

Build reusable navigation primitives.

Examples:

* Breadcrumbs
* Navigation Item
* Section Header
* Collapsible Group
* Command Palette Shell

Do not implement the actual application sidebar yet.

---

# Form Components

Create reusable form elements with consistent validation styles.

Support:

* Labels
* Helper Text
* Error Messages
* Required Indicators
* Disabled States

---

# Icon System

Use Lucide React.

Create a centralized icon wrapper to ensure consistent sizing, color, and accessibility.

Avoid direct icon usage throughout the application.

---

# Motion

Implement reusable animation utilities.

Examples:

* Fade In
* Fade Out
* Slide Up
* Slide Down
* Scale
* Modal Entrance
* Drawer Entrance
* Toast Animation
* Loading Pulse

Animations should enhance usability, not distract.

Respect reduced-motion preferences.

---

# Accessibility

Every component must:

* Support keyboard interaction
* Include proper ARIA attributes where needed
* Maintain visible focus indicators
* Meet WCAG color contrast guidelines

Accessibility is required for every component.

---

# Responsive Behavior

Design components to adapt gracefully across:

* Desktop
* Laptop
* Tablet

Avoid hardcoded widths whenever possible.

---

# Component Documentation

For each reusable component, provide:

* Purpose
* Supported variants
* Props
* Usage examples

This documentation may be placed alongside the component or in Storybook if configured.

---

# Storybook (Optional)

If appropriate for the project, configure Storybook and register all reusable components for isolated development and testing.

Do not block progress if Storybook is intentionally deferred.

---

# Quality Standards

Every component should:

* Be fully typed
* Avoid duplicated logic
* Use composition where appropriate
* Follow consistent naming
* Be easy to test
* Be easy to extend

---

# Deliverables

At completion, provide:

## Components Created

List every reusable component.

---

## Tokens Implemented

Summarize all design tokens.

---

## Theme Support

Describe light and dark mode implementation.

---

## Files Created

List all new files.

---

## Files Modified

List all modified files.

---

## Notes

Highlight any design decisions or reusable patterns introduced.

---

# Definition of Done

This task is complete only when:

* The design token system is implemented.
* Theme support works.
* Reusable UI primitives are complete.
* Layout primitives are available.
* Components are accessible.
* Components follow the official design system.
* No application pages have been built.
* No backend functionality has been introduced.
* The frontend is ready for Prompt 03.

Stop after completing the design system.

Do not proceed to the next prompt automatically.
