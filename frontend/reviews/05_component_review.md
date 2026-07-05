# 05_COMPONENT_REVIEW.md

# Prometheus Swarm Frontend — Component Review

## Objective

Component review completed on 2026-07-04.

---

# Review Findings

## Component Organization — Score: 8/10

**Strengths:**
- Shared UI primitives in `shared/ui/` with barrel exports — clean `import { Button, Card } from '@/shared/ui'`.
- Feature components organized by feature in `features/*/components/`.
- MC (Mission Control) components grouped in a `mc/` subdirectory — future-proof for multiple component groups.

**Issues:**

### [Low] Barrel file in mc/ is incomplete
- **Component:** agent.ts (barrel export)
- **Observation:** `agent.ts` re-exports 6 of 7 MC components. `AgentDrawer` is missing.
- **Impact:** Import inconsistency — some components import from `./mc`, others from `./mc/AgentDrawer` directly.
- **Recommendation:** Add `AgentDrawer` to the barrel export, or remove barrel files and use direct imports exclusively.

---

## Component Responsibilities — Score: 7/10

**Strengths:**
- Single responsibility is well-maintained: MissionHeader renders header, Timeline renders timeline, ActivityItem renders one event.
- Feature page (missions/[missionId]/page.tsx) is a thin composition layer — 134 lines of layout orchestration.

**Issues:**

### [Medium] AgentDrawer mixes data and presentation
- **Component:** AgentDrawer
- **Observation:** AgentDrawer contains hardcoded agent descriptions (`agentInfo` record with description + outputs for all 6 agents). If agent information changes, the component must be modified.
- **Impact:** Tight coupling between the drawer component and agent lore data.
- **Recommendation:** Move `agentInfo` to `features/missions/constants/` and import it. Keep AgentDrawer as a pure presentation component.

### [Low] Timeline component is presentation-only but contains stage labels
- **Component:** MissionTimeline
- **Observation:** Timeline stage labels ("Queued", "Planning", ...) are passed via props from the page, not hardcoded. Good separation.
- **Impact:** None — this is correctly architected.
- **Recommendation:** Maintain this pattern.

---

## Component Size — Score: 8/10

**Strengths:**
- All shared UI components are under 80 lines.
- MC components range from 17 (ResourceBar) to 134 (page.tsx) lines — well-scoped.
- No "God Components" identified.

**Issues:**

### [Low] AgentDrawer at 101 lines is the largest MC component
- **Component:** AgentDrawer
- **Observation:** 101 lines is perfectly reasonable for a slide-out drawer with 4 sections. No refactoring needed.
- **Recommendation:** None.

---

## Component APIs — Score: 7/10

**Strengths:**
- Consistent prop naming across shared components (`variant`, `size`, `disabled`, `loading`, `error`).
- Form controls extend native HTML attributes (`InputHTMLAttributes`, `SelectHTMLAttributes`) — predictable API.
- Button supports polymorphic rendering via extended HTML attributes.

**Issues:**

### [Medium] Card hover is a boolean prop — limits expressiveness
- **Component:** Card
- **Observation:** `hover` prop is boolean (on/off). There is no `variant` system for cards (default, interactive, compact, elevated).
- **Impact:** When a developer needs an elevated card, they must add custom styling outside the component.
- **Recommendation:** Add a `variant` prop with values like 'default', 'interactive', 'elevated', 'compact'. Keep `hover` as a sub-behavior of interactive variant.

### [Medium] Dialog props don't extend HTMLAttributes
- **Component:** Dialog
- **Observation:** Dialog has its own prop interface (open, onClose, title, children, className) and does NOT extend HTMLAttributes. This prevents passing native attributes like `aria-label` or `data-testid`.
- **Impact:** Consumers cannot customize the dialog container element's attributes.
- **Recommendation:** Extend `HTMLAttributes<HTMLDivElement>` on DialogProps and spread remaining props onto the dialog container.

### [Low] Switch has its own prop interface — doesn't extend HTMLAttributes
- **Component:** Switch
- **Observation:** Switch defines its own `{ checked, onChange, label, disabled }` interface. No extensibility for native button attributes.
- **Impact:** Cannot pass `aria-label`, `data-testid`, etc.
- **Recommendation:** Extend `ButtonHTMLAttributes<HTMLButtonElement>` and pick the Switch-specific props.

---

## Reusability — Score: 7/10

**Strengths:**
- Button, Card, Badge, Skeleton are genuinely reusable — used across dashboard, missions, settings.
- Form controls (Input, Select, Textarea, Switch) cover standard form needs.

**Issues:**

### [Medium] Missing reusable Table component
- **Component:** Missing
- **Observation:** Three different places need tables (model comparison, dataset schema, drift alert history) but no shared Table component exists. The drift page uses manual `<table>` markup.
- **Impact:** Table rendering will be inconsistent across pages. Each developer will implement their own table styling.
- **Recommendation:** Create a shared Table component with `<Table>`, `<TableHeader>`, `<TableBody>`, `<TableRow>`, `<TableCell>` sub-components. Include sort, pagination, empty state, and loading state variants.

### [Medium] No reusable EmptyState component
- **Component:** Missing
- **Observation:** 6 pages render empty states with the same pattern (icon + heading + message + optional CTA). Each page implements this manually.
- **Impact:** Inconsistent empty-state styling. Changes require editing 6 files.
- **Recommendation:** Create a shared `<EmptyState icon={...} title="..." message="..." action={...} />` component. Use it across all placeholder pages.

### [Low] No reusable Loading spinner component
- **Component:** Missing
- **Observation:** jobs/[id] and dashboard layout each implement their own loading spinner (animated border spinner). No shared component.
- **Impact:** Inconsistent loading indicators.
- **Recommendation:** Create a shared `<Spinner size="sm|md|lg" />` component and use it everywhere.

---

## Composition — Score: 7/10

**Strengths:**
- Card uses compound component pattern (Card + CardHeader + CardContent + CardFooter) — flexible and composable.
- Skeleton accepts className for custom dimensions — composition-friendly.
- Layout components (AppShell, Sidebar) use `children` slot pattern.

**Issues:**

### [Medium] MissionHeader props list is long (7 props)
- **Component:** MissionHeader
- **Observation:** MissionHeader accepts `name`, `project`, `status`, `progress`, `runtime`, `started`, `eta` as individual props. This is verbose at the call site.
- **Impact:** Component API is brittle — adding a field means adding a prop.
- **Recommendation:** Accept a mission object (typed interface) instead of individual props. This aligns with the pattern used by mock data.

---

## Design System Compliance — Score: 6/10

**Strengths:**
- All 9 shared UI components use CSS custom properties exclusively — no hardcoded values.
- Dark mode inherited automatically via `var(--color-*)` token overrides.

**Issues:**

### [High] MC components use Tailwind spacing instead of --space-* tokens
- **Component:** All MC components
- **Observation:** MC components use `px-4`, `py-2.5`, `gap-3`, etc. (Tailwind spacing classes) rather than `var(--space-4)`, `var(--space-2.5)`, etc. The `--space-*` tokens exist in tokens.css but are never referenced.
- **Impact:** The design system's spacing scale is not enforced in MC components. Changing a spacing token in CSS has no effect on MC layouts.
- **Recommendation:** Either (a) add spacing values to Tailwind's `@theme` and continue using Tailwind classes, or (b) use CSS `var(--space-*)` references via inline styles or custom classes. Choose one strategy and apply consistently.

### [Medium] Launch button uses inline styles instead of Button component
- **Component:** Mission Composer Launch button
- **Observation:** The Launch button is styled manually with inline Tailwind classes (`inline-flex items-center gap-2 h-9 px-4...`) instead of using `<Button variant="primary">`.
- **Impact:** Inconsistent button rendering. The shared Button component's loading spinner hover states and focus ring are bypassed.
- **Recommendation:** Replace inline styling with `<Button variant="primary" size="sm">`.

### [Medium] jobs/[id] page uses hardcoded colors
- **Component:** jobs/[id]/page.tsx
- **Observation:** All colors in jobs/[id] are hardcoded hex values (#E8E5DF, #C96442, #1C1B19, etc.) — zero design token usage.
- **Impact:** Page ignores dark mode entirely. This is the most functionally complete page and the most visible to users (live data from Redis).
- **Recommendation:** Replace every hex value with the corresponding `var(--color-*)` token.

---

## Loading States — Score: 4/10

**Strengths:**
- Skeleton component exists for content-placeholder loading.
- Button component has built-in loading spinner.

**Issues:**

### [High] No skeleton loading states on any mock-data page
- **Component:** All pages using mock data
- **Observation:** Dashboard, Mission Composer, and Mission Control render mock data synchronously with zero loading states. No Skeleton usage exists outside the component definition.
- **Impact:** When real APIs replace mocks, users will see blank sections during data loading.
- **Recommendation:** Replace mock data imports with React Query hooks. While mocks are in place, simulate realistic loading delays with skeleton states using the Skeleton component.

---

## Empty States — Score: 5/10

**Strengths:**
- 6 pages have empty states with icons, messages, and CTAs.

**Issues:**

### [Medium] No reusable EmptyState component
- **Component:** Missing
- **Observation:** Each page implements its own empty-state markup. Changing the empty-state design requires editing 6+ files.
- **Impact:** Maintenance burden increases linearly with the number of pages.
- **Recommendation:** Create a shared `<EmptyState>` component.

### [Low] Empty states in sections (not pages) are missing
- **Component:** Mission Control sections
- **Observation:** If the activity feed has no events, or the artifact list is empty, the sections render with headers but no content. No "No activity yet" or "No artifacts" message.
- **Impact:** Users may think the sections are broken rather than empty.
- **Recommendation:** Add conditional empty-state messages to each data-driven section.

---

## Component Inventory

| Component | Status | Notes |
|---|---|---|
| Button | ✅ Excellent | 5 variants, 4 sizes, loading state, focus-visible ring |
| Input | ✅ Good | label, description, error, disabled, forwardRef |
| Select | ✅ Good | label, error, disabled, custom chevron |
| Textarea | ✅ Good | label, error, disabled, resize-y |
| Badge | ✅ Good | 6 color variants, 2 sizes, server-compatible |
| Card | ✅ Good | hover variant, compound children, server-compatible |
| Skeleton | ✅ Good | 3 shape variants, pulse animation, server-compatible |
| Switch | ⚠️ Good | role="switch", aria-checked, disabled, needs aria-hidden on knob |
| Dialog | ⚠️ Needs work | Missing role, focus trap, aria-labelledby, enter/exit animation |
| Table | ❌ Missing | Needed for models, datasets, drift pages |
| EmptyState | ❌ Missing | Duplicated across 6+ pages |
| Spinner | ❌ Missing | Duplicated in 2 places |
| Breadcrumb | ❌ Missing | Needed for detail pages |
| ErrorBoundary | ❌ Missing | Needed for page section isolation |

---

## Component Quality Score

| Category | Score |
|---|---|
| Reusability | 7/10 |
| API Design | 7/10 |
| Consistency | 6/10 |
| Composition | 7/10 |
| Accessibility | 5/10 |
| Performance | 7/10 |
| Maintainability | 7/10 |
| Scalability | 6/10 |
| Design System Compliance | 6/10 |
| Documentation Readiness | 5/10 |

---

## Production Readiness

**Ready After Minor Refactoring** — The existing shared components (Button, Card, Badge, Skeleton, Switch) are production-quality. The main gaps are: (1) Dialog needs WAI-ARIA role and focus trap, (2) missing Table, EmptyState, Spinner, Breadcrumb shared components, (3) jobs/[id] and Launch button bypass the design system. These are straightforward to fix.

---

## Top 10 Component Improvements

1. **Add WAI-ARIA dialog pattern to Dialog** — focus trap, role, aria-modal, aria-labelledby
2. **Create shared EmptyState component** — eliminate duplication across 6+ pages
3. **Create shared Table component** — consistent data display across models, datasets, drift
4. **Refactor jobs/[id] to use design tokens** — fix dark mode on the most-used live-data page
5. **Refactor Launch button to use `<Button>` component** — consistency with shared component library
6. **Add focus restoration to AgentDrawer** — return focus to trigger element on close
7. **Create shared Spinner component** — consistent loading indicator
8. **Memoize AgentDrawer agentInfo** — move hardcoded data out of component
9. **Add Skeleton loading states to all data-driven sections** — prepare for real API integration
10. **Add variants to Card component** — extend from boolean `hover` to `variant` system
