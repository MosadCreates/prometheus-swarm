# Prometheus Swarm
# Design System

**Version:** 1.0.0

**Status:** Draft

**Owner:** Mohamed Mosad

**Last Updated:** July 2026

---

# Purpose

The Design System establishes the visual language, interaction patterns, spacing, typography, color system, iconography, and reusable design tokens for Prometheus Swarm.

Its purpose is to ensure every screen feels like part of one cohesive product rather than a collection of unrelated pages.

Every frontend implementation must follow this specification.

---

# Design Philosophy

Prometheus Swarm should feel like:

- Professional
- Intelligent
- Transparent
- Calm
- Technical
- Modern

The interface should resemble an engineering operating system rather than a traditional AI chatbot.

Users should feel like they are directing an elite engineering organization.

---

# Design Inspiration

The visual language intentionally combines ideas from several industry-leading products.

| Product | Inspiration |
|----------|-------------|
| Claude | Prompt composer and conversation |
| Cursor | Code experience |
| GitHub | Navigation and engineering workflow |
| GitHub Actions | Execution timeline |
| Railway | Live logs |
| Vercel | Dashboard polish |
| Linear | Motion and interaction quality |
| Weights & Biases | ML metrics |
| n8n | Workflow visualization |

The goal is not imitation.

The goal is consistency.

---

# Visual Identity

The interface should communicate:

Precision.

Confidence.

Transparency.

Engineering quality.

Avoid playful or decorative aesthetics.

---

# Color Philosophy

Colors communicate status rather than decoration.

The interface should remain mostly neutral.

Accent colors should indicate activity.

---

# Primary Palette

Primary

```
Blue 600
```

Used for:

- Primary Buttons
- Active Navigation
- Selected Items
- Links
- Focus States

---

Secondary

```
Indigo
```

Used for:

- Supporting Actions
- Agent Highlights
- Mission Flow

---

Success

```
Green
```

Used for:

- Completed
- Healthy
- Passed
- Successful Deployment

---

Warning

```
Amber
```

Used for:

- Validation
- Pending
- Attention

---

Error

```
Red
```

Used for:

- Failures
- Agent Errors
- Deployment Issues

---

Information

```
Cyan
```

Used for:

- Notifications
- Tips
- Documentation

---

Neutral

Gray Scale

Used for:

- Backgrounds
- Borders
- Text
- Dividers

---

# Theme Support

The system supports:

- Light Theme
- Dark Theme

Every component must support both.

No hardcoded colors.

All colors should use design tokens.

---

# Typography

Primary Font

```
Inter
```

Code Font

```
JetBrains Mono
```

---

# Font Scale

Display

48px

---

Heading 1

36px

---

Heading 2

30px

---

Heading 3

24px

---

Heading 4

20px

---

Body

16px

---

Small

14px

---

Caption

12px

---

# Font Weights

Regular

400

Medium

500

Semibold

600

Bold

700

---

# Spacing System

Base Unit

```
4px
```

Spacing Scale

```
4

8

12

16

20

24

32

40

48

64

80

96
```

Every layout should use these values.

Avoid arbitrary spacing.

---

# Border Radius

Small

6px

Medium

10px

Large

14px

Extra Large

20px

Cards should feel soft but structured.

Avoid sharp corners.

---

# Shadows

Use shadows sparingly.

Levels

Small

Medium

Large

Extra Large

Elevation should indicate hierarchy.

Not decoration.

---

# Layout Grid

Desktop

12-column grid

Maximum Width

1440px

Content Width

1280px

---

Tablet

8-column grid

---

Mobile

4-column grid

---

# Iconography

Use

Lucide Icons

Rules

- Consistent stroke width
- No mixed icon libraries
- Icons always accompany important actions
- Avoid decorative icons

---

# Buttons

Primary

Main actions.

Examples

- Execute Mission
- Deploy
- Save

---

Secondary

Supporting actions.

---

Ghost

Low-emphasis actions.

---

Danger

Destructive actions.

---

Loading

Every button supports loading state.

---

# Inputs

Input styles remain consistent.

Support

- Label
- Description
- Error
- Success
- Disabled

All forms use identical spacing.

---

# Cards

Cards are the primary content container.

Examples

- Mission Card
- Project Card
- Agent Card
- Metric Card

Every card contains:

- Header
- Content
- Footer (optional)

---

# Tables

Used for:

- Models
- Datasets
- Deployments
- Missions

Support

- Sorting
- Filtering
- Pagination
- Selection

---

# Status Badges

Standardized statuses.

Running

Waiting

Queued

Paused

Completed

Failed

Cancelled

Healthy

Offline

No custom status colors.

---

# Progress Indicators

Use

- Linear Progress
- Circular Progress
- Step Progress

Avoid endless spinners.

Always show progress when possible.

---

# Notifications

Types

Information

Success

Warning

Error

Notifications should be concise.

Never interrupt the workflow unnecessarily.

---

# Empty States

Every empty state should include:

Illustration

Explanation

Primary Action

Optional Documentation Link

Example

"No missions yet."

↓

"Create your first mission."

---

# Loading States

Prefer

Skeletons

Streaming

Incremental Rendering

Optimistic Updates

Avoid blank pages.

---

# Error States

Every error should answer:

What happened?

Why?

How can it be fixed?

What can the user do next?

---

# Motion Principles

Animations should be:

Fast

Purposeful

Subtle

Predictable

No decorative animations.

Detailed animation specifications are defined in:

08_MOTION_SYSTEM.md

---

# Accessibility

Every component must support:

Keyboard Navigation

Screen Readers

Visible Focus

High Contrast

Reduced Motion

Color Independence

Accessibility is mandatory.

---

# Responsive Design

Desktop

Full experience.

Tablet

Collapsible navigation.

Mobile

Simplified navigation.

Mission Control becomes vertically stacked.

---

# Design Tokens

All styling should be implemented through tokens.

Examples

Colors

Spacing

Typography

Radius

Shadow

Animation

Never hardcode values inside components.

---

# Naming Convention

Examples

color-primary

space-lg

radius-md

font-heading

shadow-card

duration-fast

All tokens use kebab-case.

---

# Consistency Rules

Every new screen must reuse existing:

Components

Spacing

Typography

Colors

Animations

Terminology

Do not invent new patterns unless absolutely necessary.

---

# Future Expansion

The design system should support future additions without redesign.

Examples

- Organizations
- Team Collaboration
- AI Marketplace
- Plugin System
- Multi-Workspace Support
- White Label Themes

---

# Conclusion

The Design System is the visual foundation of Prometheus Swarm.

Every page, component, animation, and interaction should reinforce a single goal:

**Build a calm, transparent, and professional AI Engineering Operating System that feels consistent, trustworthy, and scalable from the first interaction to enterprise-scale workflows.**
