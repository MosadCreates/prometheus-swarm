# Prometheus Swarm
# Motion System

**Version:** 1.0.0

**Status:** Draft

**Owner:** Mohamed Mosad

**Last Updated:** July 2026

---

# Purpose

This document defines the motion language of Prometheus Swarm.

Animations are not decorative.

They communicate:

- Progress
- System activity
- Hierarchy
- Relationships
- State changes
- User feedback

Every animation in the application must follow this specification.

---

# Motion Philosophy

Motion should make the platform feel:

- Alive
- Responsive
- Intelligent
- Calm
- Predictable
- Professional

Animations should explain what is happening, not distract from it.

---

# Core Motion Principles

## Purposeful

Every animation must communicate meaning.

Examples:

- Agent started
- Mission completed
- Deployment succeeded
- File uploaded

Avoid animations without purpose.

---

## Fast

The interface should always feel responsive.

Preferred durations:

| Duration | Use |
|-----------|-----|
| 100ms | Hover |
| 150ms | Button |
| 200ms | Card |
| 250ms | Drawer |
| 300ms | Modal |
| 400ms | Page Transition |
| 600ms | Workflow Animation |

Long animations should be avoided.

---

## Smooth

Prefer easing over linear motion.

Recommended easing:

- ease-out
- ease-in-out

Avoid bouncy effects.

---

## Consistent

The same interaction always uses the same animation.

Examples:

Every drawer opens identically.

Every modal closes identically.

Every tooltip behaves identically.

Consistency builds familiarity.

---

# Motion Categories

```
Motion

├── Page
├── Navigation
├── Mission
├── Agent
├── Workflow
├── Feedback
├── Data
├── Loading
├── Charts
└── Micro Interactions
```

---

# Page Transitions

Trigger:

Navigation between pages.

Animation:

Fade

+

Small upward movement

Duration

400ms

Purpose

Maintain context without distracting users.

---

# Sidebar

Collapse

↓

Width decreases

↓

Labels fade

↓

Icons remain visible

Expand

↓

Width increases

↓

Labels fade in

↓

Navigation shifts smoothly

Duration

250ms

---

# Cards

Hover

↓

Slight elevation

↓

Subtle shadow

↓

Border highlight

Click

↓

Quick scale down

↓

Return

Cards should feel interactive without excessive movement.

---

# Buttons

Hover

↓

Background transition

↓

Shadow increase

Press

↓

Scale to 98%

↓

Release

↓

Return

Loading

↓

Spinner replaces icon

↓

Button width remains constant

---

# Prompt Box

Focus

↓

Border highlight

↓

Glow

↓

Cursor animation

Drag File

↓

Border pulse

↓

Background highlight

↓

Upload icon animation

Submission

↓

Input locks

↓

Mission begins

↓

Mission Workspace appears

---

# Mission Creation

After pressing Execute:

Prompt

↓

Collapses upward

↓

Mission card expands

↓

Workflow fades in

↓

Scout activates

Users immediately see that work has begun.

---

# Mission Progress

Every stage updates smoothly.

Planning

↓

Research

↓

Architecture

↓

Implementation

↓

Training

↓

Evaluation

↓

Deployment

Progress should never jump abruptly.

---

# Mission Control

This is the centerpiece of the platform.

Agent activation sequence:

Waiting

↓

Glow

↓

Running pulse

↓

Connection animation

↓

Completed

↓

Success check

↓

Next agent activates

Only one primary execution path should be highlighted.

---

# Workflow Graph

Connections animate while work progresses.

Inactive

↓

Gray

Running

↓

Animated gradient

Completed

↓

Solid success color

Failed

↓

Red

↓

Pulse

Workflow should resemble electricity flowing through a circuit.

---

# Agent Node

Waiting

↓

Low opacity

Running

↓

Glow

↓

Pulse

↓

Live indicator

Completed

↓

Checkmark

↓

Glow fades

Failed

↓

Red border

↓

Shake once

↓

Error badge

---

# Agent Drawer

Opening

↓

Slide from right

↓

Fade

↓

Background blur

Closing

↓

Reverse animation

Duration

250ms

---

# Timeline

Each event appears with:

Fade

↓

Slide upward

↓

Timestamp animation

Newest event briefly highlights.

---

# Logs

Streaming logs should appear line-by-line.

Each new entry:

Fade

↓

Slide upward

↓

Auto-scroll

Avoid sudden jumps.

---

# Charts

Metric updates animate smoothly.

Accuracy

↓

Line grows

Loss

↓

Curve updates

GPU

↓

Bar transitions

Avoid redrawing entire charts.

---

# File Explorer

Folder

Expand

↓

Rotate arrow

↓

Children slide down

Collapse

↓

Reverse

---

# Code Viewer

File Switch

↓

Fade

↓

Syntax Highlight

↓

Scroll restoration

No flashing.

---

# Notifications

Toast

↓

Slide from top-right

↓

Fade

↓

Auto-dismiss

↓

Fade out

Critical alerts remain visible.

---

# Modal

Open

↓

Scale

↓

Fade

↓

Background blur

Close

↓

Reverse

Duration

300ms

---

# Loading States

Avoid generic spinners whenever possible.

Preferred loading patterns:

- Skeletons
- Streaming content
- Progressive rendering
- Placeholder cards

Spinners should only appear for very short operations.

---

# Success Animations

Examples:

Mission Complete

↓

Green progress

↓

Check icon

↓

Summary card

Deployment Complete

↓

Success badge

↓

Endpoint appears

↓

Confetti should NOT be used.

---

# Error Animations

Errors should attract attention without causing stress.

Examples:

- Red border
- Shake once
- Error icon
- Retry button

Never loop error animations continuously.

---

# Empty States

Illustration

↓

Message

↓

Primary Action

Optional fade-in.

---

# Hover States

Hover effects should communicate interactivity.

Use:

- Border
- Background
- Shadow
- Cursor

Avoid excessive movement.

---

# Keyboard Navigation

Focus transitions should animate subtly.

Visible focus ring.

No flashing.

---

# Reduced Motion

Respect the user's operating system preference.

When reduced motion is enabled:

- Disable transitions longer than 100ms
- Remove scaling effects
- Remove pulses
- Replace animated graphs with instant updates

Accessibility takes priority.

---

# Animation Performance

Target:

60 FPS

Use:

- transform
- opacity

Avoid animating:

- width
- height
- left
- top

unless absolutely necessary.

Prefer GPU-accelerated animations.

---

# Framer Motion Guidelines

Use Framer Motion for:

- Page transitions
- Drawers
- Modals
- Agent nodes
- Workflow graph
- Notifications
- Mission transitions

Avoid using Framer Motion for:

- Large tables
- Code editor
- Thousands of timeline entries

---

# Motion Tokens

All animations should use centralized tokens.

Examples:

```
duration-fast
duration-normal
duration-slow

ease-standard
ease-out
ease-in-out

scale-hover
scale-press

opacity-hidden
opacity-visible
```

Never hardcode animation values.

---

# Signature Animations

Prometheus Swarm should have a few recognizable animations.

### Mission Launch

Prompt transforms into a live mission workspace.

---

### Swarm Activation

Agents activate one after another with animated connections.

---

### Live Workflow

Execution flows through the graph in real time.

---

### Artifact Creation

When an artifact is generated:

- Appears in the explorer
- Brief highlight
- Counter increments
- Timeline updates

---

### Mission Complete

Mission graph settles.

Progress reaches 100%.

Summary fades in.

Suggested next actions appear.

---

# Motion Checklist

Before implementing an animation, verify:

- Does it communicate meaning?
- Is it fast?
- Is it consistent?
- Is it accessible?
- Does it improve understanding?
- Does it maintain 60 FPS?
- Does it respect reduced motion?
- Does it reuse motion tokens?

If any answer is "No", redesign the animation.

---

# Conclusion

Motion is a core part of the Prometheus Swarm experience.

It should reinforce transparency, communicate system state, and make the swarm feel like a living engineering organization.

Animations are never decorative.

They exist to help users understand, trust, and confidently interact with autonomous AI systems.
