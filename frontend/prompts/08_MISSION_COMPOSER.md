# 08_MISSION_COMPOSER.md

# Prometheus Swarm Frontend — Mission Composer

## Read First

Before starting this task, read:

* 00_MASTER_PROMPT.md
* 01_PRODUCT_VISION.md
* 02_DESIGN_PRINCIPLES.md
* 03_INFORMATION_ARCHITECTURE.md
* 04_USER_FLOWS.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 09_MISSION_CONTROL.md
* 10_AGENT_EXPERIENCE.md
* 12_FRONTEND_ARCHITECTURE.md

Follow these documents exactly.

---

# Objective

Build the Mission Composer.

This is the primary interface where users create a new AI mission.

Unlike a traditional chatbot, users should feel they are preparing an engineering task for an intelligent autonomous system.

The experience should be simple enough for beginners while exposing advanced controls progressively.

---

# Scope

Frontend only.

Do NOT implement:

* AI execution
* Agent orchestration
* Backend APIs
* File processing
* Model execution
* Dataset processing
* Training logic

Use mock data and placeholder interactions only.

---

# Pages

Build:

```text
/missions/new
```

The Mission Composer should also be embeddable as a reusable component.

---

# Design Inspiration

Combine ideas from:

* Claude (clean composer)
* Cursor (context awareness)
* Linear (minimal interactions)
* GitHub (structured forms)
* Railway (professional engineering feel)

Create an original Prometheus Swarm experience.

---

# Layout

Structure:

```text
Page Header

↓

Mission Workspace

├── Left Panel
│     Context & Resources
│
├── Center
│     Mission Composer
│
└── Right Panel
      Mission Configuration
```

Desktop uses three panels.

Tablet collapses side panels into drawers.

---

# Header

Display:

* Page title
* Breadcrumbs
* Current project
* Save Draft
* Launch Mission

Launch Mission should only trigger a mock flow.

---

# Center Panel

This is the primary workspace.

Include:

* Large multiline prompt input
* Auto-resizing textarea
* Placeholder guidance
* Character counter
* Prompt templates
* Attach file button
* Drag-and-drop upload area
* Voice input placeholder
* Clear prompt button

The prompt input should be the visual focus.

---

# Prompt Suggestions

Below the input, display optional suggestions.

Examples:

* Build a model
* Analyze my dataset
* Train an object detector
* Generate documentation
* Optimize performance
* Create deployment pipeline

Clicking inserts sample text.

---

# File Upload

Support UI for:

* Drag and drop
* Browse files
* Multiple files
* Upload progress (mock)
* Remove attachment
* File preview
* File type icons

No actual upload logic.

---

# Left Panel

Display project context.

Sections:

* Current Project
* Recent Files
* Selected Datasets
* Previous Missions
* Recent Models

Allow users to select or deselect items.

Use mock data only.

---

# Right Panel

Mission configuration.

Include:

## Mission Name

Optional editable field.

---

## Priority

Options:

* Low
* Normal
* High
* Critical

---

## Execution Mode

UI only.

Examples:

* Fast
* Balanced
* Maximum Quality

---

## Resources

Placeholder controls for:

* Compute
* Memory
* Storage

No real configuration.

---

## Expected Outputs

Checkboxes:

* Code
* Model
* Documentation
* Report
* Dataset
* Deployment Package

---

## Notifications

Toggle:

* Notify on completion

UI only.

---

# Context Chips

Display attached context as removable chips.

Examples:

* Dataset A
* README.md
* model.py
* Project Documentation

---

# Prompt Templates

Create a reusable template selector.

Categories:

* Machine Learning
* Deep Learning
* Data Analysis
* Computer Vision
* NLP
* Deployment
* Automation

Selecting a template fills the prompt.

---

# Validation

Provide frontend validation for:

* Empty prompt
* Maximum length
* Unsupported file type (mock)
* Missing project (mock)

Display inline feedback.

---

# Launch Flow

When the user presses **Launch Mission**:

Show:

```text
Validate

↓

Mission Summary

↓

Confirmation Dialog

↓

Mission Created

↓

Navigate to Mission Control
```

Everything is mocked.

No backend interaction.

---

# Draft Support

Allow:

* Save Draft (mock)
* Discard Draft
* Restore Draft

Persist locally only if needed.

No server persistence.

---

# Components to Build

Create reusable components:

* MissionComposer
* PromptEditor
* PromptSuggestions
* FileUploader
* AttachmentList
* ContextPanel
* ConfigurationPanel
* MissionSummary
* LaunchDialog
* ResourceSelector
* OutputSelector
* PrioritySelector
* ExecutionModeSelector
* PromptTemplateCard
* ContextChip

All components should be reusable.

---

# Empty States

Design empty states for:

* No project selected
* No recent files
* No datasets
* No templates

Guide the user toward the next action.

---

# Loading States

Provide skeletons for:

* Context panel
* Prompt templates
* File list
* Configuration panel

Reuse the design system.

---

# Motion

Implement subtle animations for:

* Panel appearance
* Drag-and-drop
* File upload progress
* Prompt suggestions
* Launch dialog
* Button feedback

Follow the Motion System.

Respect reduced-motion preferences.

---

# Accessibility

Ensure:

* Keyboard navigation
* Proper focus order
* Accessible labels
* Screen reader compatibility
* Semantic form elements

All controls must be usable without a mouse.

---

# Responsive Design

Desktop:

* Three-panel workspace

Laptop:

* Narrow side panels

Tablet:

* Collapsible drawers

Maintain a comfortable writing experience at all sizes.

---

# Mock Data

Create separate mock data for:

* Projects
* Recent Files
* Datasets
* Templates
* Previous Missions
* Configuration Options

Do not hardcode data inside components.

---

# Visual Quality

The Mission Composer should feel:

* Calm
* Focused
* Intelligent
* Professional
* Trustworthy

Whitespace and typography should guide attention to the prompt editor.

---

# Deliverables

Provide:

## Pages Created

List all pages.

---

## Components Created

List every reusable component.

---

## Mock Data Files

List all mock data sources.

---

## Files Created

List all new files.

---

## Files Modified

List all modified files.

---

## Notes

Highlight assumptions, reusable patterns, and future backend integration points.

---

# Definition of Done

This task is complete only when:

* Mission Composer page is complete.
* Three-panel layout works.
* Prompt editor is implemented.
* File upload UI exists.
* Context panel is functional with mock data.
* Configuration panel is complete.
* Launch flow is fully mocked.
* Theme support works.
* Responsive layouts work.
* Accessibility requirements are met.
* No backend functionality has been implemented.
* No undocumented APIs have been introduced.

Stop after completing the Mission Composer.

Do not proceed to Mission Control automatically.
