# 10_AGENT_DETAILS.md

# Prometheus Swarm Frontend — Agent Details

## Read First

Before starting, read:

* 00_MASTER_PROMPT.md
* 01_PRODUCT_VISION.md
* 02_DESIGN_PRINCIPLES.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 09_MISSION_CONTROL.md
* 10_AGENT_EXPERIENCE.md
* 12_FRONTEND_ARCHITECTURE.md

These documents define the expected agent experience.

---

# Objective

Build the Agent Details experience.

This page allows users to inspect a single AI agent participating in a mission.

The goal is transparency.

Users should understand:

* What this agent is responsible for.
* What it has already completed.
* What it is doing now.
* What tools it has used.
* What outputs it created.
* What will happen next.

No backend implementation.

Use realistic mock data.

---

# Scope

Frontend only.

Do NOT implement:

* Agent execution
* LLM calls
* Backend APIs
* Logs streaming
* Tool execution
* Code generation
* Model inference

Everything is powered by structured mock data.

---

# Route

Create:

```text
/missions/[missionId]/agents/[agentId]
```

The page should also work as a full-screen drawer opened from Mission Control.

---

# Overall Layout

Structure:

```text
┌─────────────────────────────────────────────────────────────┐
│ Agent Header                                                │
├────────────────────────────┬────────────────────────────────┤
│                            │                                │
│ Agent Overview             │ Live Activity                 │
│                            │                                │
├────────────────────────────┼────────────────────────────────┤
│ Tool Usage                 │ Generated Outputs             │
├────────────────────────────┴────────────────────────────────┤
│ Timeline                                                     │
└─────────────────────────────────────────────────────────────┘
```

Desktop uses a two-column layout.

Tablet stacks sections vertically.

---

# Agent Header

Display:

* Agent Avatar
* Agent Name
* Role
* Current Status
* Mission Name
* Started Time
* Runtime
* Progress Bar

Actions:

* Open Mission
* View Outputs
* Export Report (UI only)

---

# Agent Overview

Display:

## Description

Explain the purpose of the agent.

---

## Responsibilities

Examples:

* Planning
* Coding
* Testing
* Training
* Reviewing

---

## Current Objective

Show current assigned task.

---

## Current State

Examples:

* Waiting
* Executing
* Reviewing
* Completed
* Failed

---

# Live Activity

Display chronological events.

Each event contains:

* Timestamp
* Action
* Description
* Status

Examples:

* Reading repository
* Selecting tools
* Building model
* Running tests
* Writing documentation

Support expanding each event.

---

# Expand Activity

Expanded event displays:

* Inputs
* Outputs
* Notes
* Related files
* Generated code (mock)
* Logs (mock)

Use reusable components.

---

# Tool Usage

Display every tool used.

Each Tool Card includes:

* Tool Name
* Category
* Status
* Execution Time
* Purpose

Examples:

* Python
* Search
* File Reader
* Training Pipeline
* Documentation Generator

Mock data only.

---

# Generated Outputs

Display everything produced by the agent.

Examples:

* Python files
* Markdown
* JSON
* Images
* Reports
* Models

Each output card supports:

* Preview
* Expand
* Copy
* Download (UI only)

---

# Code Viewer

If an output is code:

Open Monaco Editor in read-only mode.

Features:

* Syntax highlighting
* Copy button
* Line numbers
* Full-screen mode

No editing.

---

# Timeline

Visualize agent progress.

Example:

```text
Planning

↓

Research

↓

Implementation

↓

Validation

↓

Completed
```

Highlight current stage.

---

# Statistics

Display summary cards.

Examples:

* Tasks Completed
* Files Generated
* Tools Used
* Outputs Produced
* Duration

Static values only.

---

# Related Agents

Display other agents in the mission.

Each card:

* Avatar
* Name
* Role
* Status

Click navigates to another mock Agent Details page.

---

# Notes Panel

Display mock observations.

Examples:

* Waiting for validation.
* Completed code generation.
* Reviewing outputs.

Frontend only.

---

# Search

Allow searching within the agent's activity history.

Use local mock data.

---

# Filters

Support filtering by:

* Status
* Tool
* Output Type

Frontend only.

---

# Components to Build

Create reusable components:

* AgentHeader
* AgentOverview
* AgentStats
* AgentTimeline
* ActivityFeed
* ActivityCard
* ToolCard
* ToolUsagePanel
* OutputCard
* OutputGallery
* CodeViewer
* NotesPanel
* RelatedAgentCard

Keep components modular and reusable.

---

# Empty States

Provide empty states for:

* No activity
* No outputs
* No tools
* No related agents

Guide the user appropriately.

---

# Loading States

Create skeletons for:

* Agent header
* Activity feed
* Tool cards
* Output gallery
* Timeline

Reuse shared Skeleton components.

---

# Mock Data

Store separately:

* Agent profile
* Activities
* Tool usage
* Outputs
* Timeline
* Statistics
* Related agents

Never embed mock data directly inside components.

---

# Motion

Implement subtle animations for:

* Activity expansion
* Timeline progression
* Status changes
* Output previews
* Drawer transitions

Follow the Motion System.

Animations should improve comprehension.

---

# Accessibility

Ensure:

* Keyboard navigation
* Proper focus order
* Screen reader compatibility
* Semantic HTML
* Accessible controls

The page should be fully usable without a mouse.

---

# Responsive Design

Desktop:

* Two-column workspace

Laptop:

* Narrower panels

Tablet:

* Single-column layout

Maintain readability and usability across supported devices.

---

# Visual Style

The Agent Details page should feel:

* Transparent
* Intelligent
* Calm
* Professional

Avoid unnecessary visual noise.

The user should feel they are inspecting a highly capable engineering specialist.

---

# Deliverables

Provide:

## Components Created

List every reusable component.

---

## Layout Summary

Explain the page structure.

---

## Mock Data Files

List all mock data sources.

---

## Files Created

List every new file.

---

## Files Modified

List every modified file.

---

## Notes

Document assumptions, reusable patterns, and future integration points.

---

# Definition of Done

This task is complete only when:

* Agent Details page is complete.
* Agent Overview is implemented.
* Activity Feed works with mock data.
* Tool Usage panel is complete.
* Generated Outputs section is implemented.
* Code Viewer works in read-only mode.
* Timeline is complete.
* Statistics cards are implemented.
* Related Agents section works.
* Responsive behavior is complete.
* Accessibility requirements are met.
* Theme support works.
* No backend functionality has been implemented.
* No undocumented APIs have been introduced.

Stop after completing Agent Details.

Do not proceed to Artifact Explorer or any other feature automatically.
