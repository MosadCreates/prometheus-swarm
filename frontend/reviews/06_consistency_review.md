# 06_CONSISTENCY_REVIEW.md

# Prometheus Swarm Frontend — Consistency Review

## Objective

Consistency review completed on 2026-07-04.

---

# Review Findings

## Visual Consistency — Score: 6/10

**Strengths:**
- Cool-tone color system (blue primary, indigo secondary, emerald green for success) is consistent across dashboard, missions, settings, and empty-state pages.
- Agent colors are applied consistently (Scout=blue, Forge=purple, Furnace=red, Dissect=green, Arbiter=amber, Harbor=cyan) across Mission Control, AgentDrawer, and Activity Feed.
- Typography (Inter for UI, JetBrains Mono for code) is applied consistently.

**Issues:**

### [High] Warm landing page vs cool dashboard creates two visual identities
- **Area:** Colors
- **Observation:** Landing page (`/`) uses warm copper (#C96442), cream (#F7F6F3), and dark brown (#1C1B19). Dashboard pages use cool blue (#2563EB), gray (#f9fafb), and near-black (#111827). These are two completely different color palettes.
- **Impact:** The product lacks a single visual identity. Navigation from landing → dashboard feels like switching products.
- **Recommendation:** Either (a) convert the landing page to the cool design system, or (b) define both as intentional "brand modes" with a clear transition between them.

### [High] jobs/[id] page uses the warm palette — out of place in the dashboard
- **Area:** Colors
- **Observation:** jobs/[id] uses #C96442 (copper), #E8E5DF (warm border), #F7F6F3 (warm bg) — matching the landing page, not the dashboard. This is the most data-rich page with live Redis data.
- **Impact:** Users navigating from dashboard → feed → jobs/[id] experience a color discontinuity.
- **Recommendation:** Refactor jobs/[id] to use the cool-tone design tokens matching all other dashboard pages.

---

## Spacing System — Score: 7/10

**Strengths:**
- Tailwind's standard spacing scale (4px base) is used consistently across all components and pages.
- No obvious spacing outliers — padding, margins, and gaps follow a consistent rhythm.

**Issues:**

### [Medium] --space-* tokens defined but unused
- **Area:** Spacing
- **Observation:** tokens.css defines an 11-step spacing scale (`--space-1` through `--space-24`), but no component references these variables. All spacing uses Tailwind utility classes directly.
- **Impact:** If the spacing scale needs to be globally adjusted, updating tokens.css has no effect. Developers must update each Tailwind class individually.
- **Recommendation:** Either (a) remove unused spacing tokens from tokens.css to avoid misleading future developers, or (b) add spacing values to Tailwind's @theme so Tailwind classes derive from the token values.

---

## Typography — Score: 7/10

**Strengths:**
- Inter (sans) for UI text, JetBrains Mono for code — consistent across all pages.
- Heading hierarchy is respected: h1 for page titles, h2 for section headers, h3 for card titles, h4 for subsection headers.
- Font weights follow a predictable pattern (semibold for headings, normal for body, medium for labels).

**Issues:**

### [Medium] Fraunces (display font) only on landing page
- **Area:** Typography
- **Observation:** globals.css @theme defines `--font-display: "Fraunces", serif` with bold weight, used for the landing page hero. No other page uses it.
- **Impact:** Another element of the "two identities" problem. The display font gives the landing page a editorial feel that doesn't carry into the product.
- **Recommendation:** Either remove Fraunces and standardize on Inter across all pages, or carry Fraunces into the dashboard as a heading accent font for brand consistency.

---

## Component Consistency — Score: 6/10

**Strengths:**
- Shared UI components are used consistently on dashboard and settings pages.
- Empty-state pattern (icon + heading + message + CTA) is visually consistent across 6 pages.

**Issues:**

### [High] Launch button bypasses shared Button component
- **Area:** Components
- **Observation:** Mission Composer's Launch button uses inline classes instead of `<Button variant="primary">`. It has no loading spinner, no focus-visible ring, and no disabled styling from the shared component.
- **Impact:** Inconsistent button behavior. If Button's disabled styling or loading behavior improves, the Launch button won't benefit.
- **Recommendation:** Replace inline styling with `<Button variant="primary" size="sm" disabled={!prompt.trim()}>`.

### [Medium] jobs/[id] uses raw HTML tables instead of styled components
- **Area:** Components
- **Observation:** The job detail page's stat cards and event log use manual `<div>` layouts with inline styles — no Card, Badge, or Skeleton components are used.
- **Impact:** Inconsistent visual language. The stat cards on dashboard use design tokens; job detail stat cards use hardcoded warm colors.
- **Recommendation:** Refactor job detail stat cards to use the `<Card>` component with design tokens.

### [Low] No shared Table component — pages implement tables differently
- **Area:** Components
- **Observation:** The drift page uses a native `<table>` element; other data lists use flexbox `<div>` layouts. No standardized table pattern exists.
- **Impact:** As more data-rich pages are built (model comparison, dataset schema), table inconsistency will compound.
- **Recommendation:** Create a shared Table component before building more data-heavy pages.

---

## Layout Consistency — Score: 6/10

**Strengths:**
- Dashboard, Mission Composer, Mission Control, and Settings all use AppShell — consistent chrome.
- Sidebar behavior (expand/collapse, active state, recent items) is consistent across AppShell pages.

**Issues:**

### [Medium] AppShell not used on dashboard and jobs/[id]
- **Area:** Layout
- **Observation:** `/dashboard` and `/jobs/[id]` do not use AppShell and render independently. The root layout's top nav bar provides navigation instead.
- **Impact:** Two different navigation systems exist. Dashboard users see a top nav; mission pages see a sidebar. Inconsistent spatial navigation.
- **Recommendation:** Move all authenticated pages to a common layout group with AppShell. The top nav bar should only appear on unauthenticated pages (landing, login, register).

---

## Navigation — Score: 7/10

**Strengths:**
- Sidebar groups pages logically (Dashboard, Projects, Missions under mission-related; Models, Datasets, Training under model-related; Deployments; Settings).
- Active state highlighting is consistent across sidebar items.

**Issues:**

### [Medium] No breadcrumbs on detail pages
- **Area:** Navigation
- **Observation:** Mission Control (/missions/[id]) and New Mission (/missions/new) have no breadcrumb navigation. Users cannot easily navigate up to the missions list.
- **Impact:** Users navigating deep into the app lose spatial context.
- **Recommendation:** Add breadcrumbs: "Missions > {mission name}" on Mission Control, "Missions > New Mission" on composer.

### [Low] Sidebar "Recent Missions" and "Recent Projects" use mock data
- **Area:** Navigation
- **Observation:** The sidebar's recent sections show hardcoded mock items from mock.ts. These will not update as real missions are created.
- **Impact:** Sidebar quickly becomes stale and misleading.
- **Recommendation:** Wire sidebar recents to real data (Redis or local storage) before production.

---

## Motion Consistency — Score: 5/10

**Strengths:**
- 200ms transition duration (`--duration-normal`) is used consistently for hover states and Button transitions.
- Sidebar collapse uses 300ms (`--duration-slow`) — appropriately slower for layout animation.

**Issues:**

### [Medium] Dialog and AgentDrawer have no consistent motion pattern
- **Area:** Motion
- **Observation:** AgentDrawer slides in from right (0.2s ease-out CSS keyframe). Dialog appears instantly with no animation. These are the two primary overlay components and they animate differently.
- **Impact:** Users perceive inconsistent quality — the drawer feels polished, the dialog feels abrupt.
- **Recommendation:** Standardize overlay entry/exit animations. Both should use the same duration and easing (recommend 200ms ease-out for entry, 150ms ease-in for exit).

### [Low] Progress bar uses 500ms — inconsistent with motion token system
- **Area:** Motion
- **Observation:** MissionHeader's progress bar uses `duration-500` (Tailwind's 500ms). The design system defines `--duration-slow` as 300ms. This animation is 200ms slower than the slowest token.
- **Impact:** Minor inconsistency in perceived speed of feedback.
- **Recommendation:** Use `duration-[var(--duration-slow)]` (300ms) for the progress transition.

---

## Status Indicators — Score: 7/10

**Strengths:**
- Status colors (success=green, warning=amber, error=red, info=cyan, running=blue) are applied consistently via the Badge component across all pages.
- Badge uses semantic color names (not agent names) — correct abstraction.

**Issues:**

### [Low] Agent status dots are color-only indicators without labels
- **Area:** Status
- **Observation:** Activity feed shows running/completed/waiting status as colored dots (green/blue/gray) with no text label. Agent cards show a colored dot between name and task.
- **Impact:** Colorblind users cannot distinguish status without reading the event action text.
- **Recommendation:** Add visually-hidden text labels to status dots, or use text-based status badges instead of dots.

---

## Theme Consistency — Score: 5/10

**Strengths:**
- Dark mode is consistently applied across all pages using the `[data-theme="dark"]` CSS mechanism.
- Shared UI components, MC components, dashboard, and settings all use CSS variables that respond to theme changes.

**Issues:**

### [Critical] jobs/[id] page ignores dark mode entirely
- **Area:** Theme
- **Observation:** jobs/[id] uses hardcoded warm hex colors from the landing page palette. These do not change when the theme toggles. The page appears in light-mode colors even in dark mode.
- **Impact:** Users with dark mode enabled get a broken visual experience on the most functional live-data page.
- **Recommendation:** Refactor all colors in jobs/[id] to use `var(--color-*)` tokens.

### [Medium] Landing page has no dark mode
- **Area:** Theme
- **Observation:** The landing page uses warm palette (#F7F6F3 bg, #C96442 accent) with no dark-mode overrides. In dark mode, it retains light-mode colors.
- **Impact:** Users who set dark mode and visit the landing page see a light page jarringly inserted between dark auth pages.
- **Recommendation:** Define dark-mode overrides for the warm palette, or convert the landing page to the cool design system.

---

## Final Consistency Checklist

| Item | Status | Notes |
|---|---|---|
| Colors | ⚠️ Minor Issues | Dual warm/cool systems; jobs/[id] uses wrong palette |
| Typography | ✅ Pass | Inter + JetBrains Mono consistent; Fraunces only on landing |
| Spacing | ✅ Pass | Tailwind spacing used consistently |
| Icons | ✅ Pass | Lucide icons, consistent stroke weight, correct sizing |
| Buttons | ⚠️ Minor Issues | Launch button bypasses shared Button component |
| Inputs | ✅ Pass | All form controls share design language |
| Cards | ✅ Pass | Shared Card component used consistently |
| Tables | ❌ Major Issues | No shared Table component; manual implementations vary |
| Dialogs | ⚠️ Minor Issues | Dialog and AgentDrawer animate differently |
| Navigation | ✅ Pass | Sidebar consistent; breadcrumbs missing |
| Motion | ⚠️ Minor Issues | Duration tokens not always respected; reduced-motion not supported |
| Themes | ❌ Major Issues | jobs/[id] ignores dark mode; landing has no dark mode |
| Loading States | ❌ Major Issues | No skeleton states, no shared Spinner |
| Empty States | ✅ Pass | Visually consistent, but no shared component |
| Error States | ❌ Major Issues | No consistent error pattern; only error.tsx exists |
| Status Indicators | ✅ Pass | Badge component consistent |
| Language | ✅ Pass | Terminology consistent ("mission", "agent", "deployment") |
| Responsive | ❌ Major Issues | Desktop-only; no breakpoints in Mission Control |

---

## Consistency Score Summary

| Category | Score |
|---|---|
| Visual Consistency | 6/10 |
| Component Consistency | 6/10 |
| Layout Consistency | 6/10 |
| Typography | 7/10 |
| Motion | 5/10 |
| Navigation | 7/10 |
| Theme Consistency | 5/10 |
| Forms | 7/10 |
| Dashboards | 7/10 |
| Overall Consistency | 6/10 |

---

## Design System Compliance

**Good** — The design system is well-defined in tokens.css and adhered to by shared UI components, MC components, dashboard, and settings. The primary compliance gaps are jobs/[id] (warm palette, no tokens), the landing page (dual warm palette), and the Launch button (inline styles bypassing Button component). Estimated compliance: ~70% of the codebase uses design tokens.

---

## Production Readiness

**Ready After Minor Consistency Fixes** — The product is visually cohesive across ~85% of pages. The two critical fixes are: (1) refactor jobs/[id] to use design tokens (fixes dark mode + palette consistency), (2) unify the dual warm/cool color systems. After these, the product will feel like a single application rather than two separate interfaces.

---

## Highest-Priority Consistency Issues

1. **Refactor jobs/[id] to use design tokens** — fixes dark mode, palette consistency, and theme compliance
2. **Create shared EmptyState and Spinner components** — consistent loading and empty patterns
3. **Add breadcrumbs to detail pages** — improved navigation context
4. **Standardize overlay animations** — Dialog and AgentDrawer should animate consistently
5. **Refactor Launch button to use shared Button component** — consistent button behavior
