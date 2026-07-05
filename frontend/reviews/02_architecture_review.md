# 02_ARCHITECTURE_REVIEW.md

# Prometheus Swarm Frontend — Architecture Review

## Objective

Architecture review completed on 2026-07-04.

---

# Review Findings

## Project Structure — Score: 8/10

**Strengths:**
- Feature-first folder structure (`features/`, `shared/`, `services/`, `providers/`, `hooks/`, `types/`, `config/`) is well-organized and scales cleanly.
- Mock data is separated into `features/*/constants/` — never embedded in components.
- Path alias `@/*` → `./src/*` works correctly, keeping imports clean.

**Issues:**

### [Low] Barrel exports inconsistent
- **Area:** Folder Structure
- **Observation:** `features/missions/components/mc/agent.ts` acts as a barrel file but only 6 of 7 components are re-exported. `AgentDrawer` is imported directly from its file.
- **Impact:** Maintainers must remember which import path to use for each component.
- **Recommendation:** Add `AgentDrawer` to the barrel export, or remove the barrel file entirely and use direct imports consistently.

### [Low] Mix of kebab-case and camelCase in feature folders
- **Area:** Folder Structure
- **Observation:** Feature folders use kebab-case for index files and multi-word paths but direct file names are camelCase. No clear enforcement.
- **Impact:** Minor cognitive friction when navigating the codebase.
- **Recommendation:** Codify a naming convention (prefer kebab-case for files) and add a lint rule.

---

## Component Architecture — Score: 7/10

**Strengths:**
- 9 shared UI components (Button, Input, Select, Textarea, Badge, Card, Skeleton, Switch, Dialog) with consistent prop patterns.
- All form controls use `forwardRef` — form-library ready.
- Server-compatible components (Badge, Card, Skeleton) correctly omit `'use client'`.

**Issues:**

### [Medium] Dialog lacks WAI-ARIA dialog pattern
- **Area:** Components
- **Observation:** The shared Dialog component has no `role="dialog"`, no `aria-modal`, no focus trapping, no initial focus management, and no `aria-labelledby` linking to the title.
- **Impact:** Screen reader users cannot identify or interact with dialog content. Keyboard users can Tab out of the dialog.
- **Recommendation:** Add `role="dialog"`, `aria-modal="true"`, `aria-labelledby` referencing the title, and implement focus trapping (trap Tab/Shift+Tab within the dialog).

### [Medium] No ErrorBoundary component
- **Area:** Components
- **Observation:** There is no reusable ErrorBoundary component in `shared/ui`. The only error boundary is the app-level `error.tsx`.
- **Impact:** A crash in one section of Mission Control (e.g., the Activity Feed) can take down the entire page.
- **Recommendation:** Create a reusable `<ErrorBoundary>` component with fallback UI that matches the design system.

### [Low] Button component not used consistently
- **Area:** Components
- **Observation:** The shared `<Button>` component exists but Mission Composer's Launch button uses inline styles (`inline-flex items-center gap-2 h-9 px-4 rounded-[var(--radius-md)] bg-[var(--color-primary)] ...`) instead of `<Button variant="primary" size="sm">`.
- **Impact:** If Button's design changes (e.g., new hover state or loading spinner position), the Launch button will not update.
- **Recommendation:** Refactor all buttons to use the shared `<Button>` component.

---

## Design System Usage — Score: 6/10

**Strengths:**
- CSS custom properties defined comprehensively in `tokens.css` (colors, typography, spacing, shadows, animation, layout).
- Dark mode via `[data-theme="dark"]` selector — clean override pattern.
- Agent colors are semi-semantic (matching product identity).

**Issues:**

### [High] Token duplication between tokens.css and Tailwind @theme
- **Area:** Styling
- **Observation:** Agent colors and status colors are defined identically in both `tokens.css` (`:root`) and `globals.css` (`@theme`). The `@theme` block also defines warm-landing-page colors that don't exist in tokens. Core tokens (background, text, spacing, shadows, radii) are NOT in `@theme` and cannot be used via Tailwind utilities.
- **Impact:** Double maintenance burden. Some values only work as `var(--*)`, others only as Tailwind classes. Developers must know both systems.
- **Recommendation:** Consolidate to one source of truth. Either: (a) Move everything to `@theme` and use Tailwind utilities everywhere, or (b) keep CSS variables as the single source and remove the `@theme` agent/status duplication.

### [High] jobs/[id] page hardcodes hex colors — ignores design system
- **Area:** Styling
- **Observation:** The most functionally complete page uses hardcoded warm tones (#C96442, #E8E5DF, #1C1B19) instead of design tokens.
- **Impact:** Page will not respond to theme changes, breaking dark mode for live-data users.
- **Recommendation:** Refactor all colors to `var(--color-*)` tokens.

### [Medium] Hardcoded warm colors in landing page globals.css
- **Area:** Styling
- **Observation:** `.btn-accent` (#C96442), `.input-field` (#C96442), `.sidebar-item.active` (#C96442), `::selection` (#C96442) are hardcoded in globals.css.
- **Impact:** These bypass the design system and create an alternate "warm" theme that only applies to landing/marketing pages.
- **Recommendation:** Define landing page tokens explicitly in `@theme` (which is partially done) and replace hardcoded values with `var(--warm-*)` references.

---

## State Management — Score: 5/10

**Strengths:**
- Zustand installed and available in package.json for future global state.
- TanStack Query installed for server state management.
- Local useState used appropriately for simple component state (prompt text, expanded events, filter selection).

**Issues:**

### [Medium] No global state management in use yet
- **Area:** State
- **Observation:** All data flows through mock constants imported directly into components. No React Query, Zustand store, or context (beyond auth/theme) is used for application data.
- **Impact:** When real API integration begins, every component will need to be refactored from `import { mockData }` to `useQuery()` or store selectors.
- **Recommendation:** Establish a service layer pattern (e.g., `services/missionService.ts`) with typed fetch functions and React Query hooks. Wire mock data through the service layer so components import from services, not mock constants directly.

### [Low] No data fetching abstraction layer
- **Area:** State
- **Observation:** All API calls in existing pages (jobs, feed, drift) use raw `fetch()` calls with manual loading/error state management. No hooks, no React Query, no error normalization.
- **Impact:** Each page duplicates the same fetch → loading → error pattern. Inconsistent behavior (jobs/[id] has loading spinner but no error handling).
- **Recommendation:** Create a `useApiQuery` hook wrapping React Query's `useQuery` with consistent error handling, loading state, and auth token injection.

---

## Routing — Score: 8/10

**Strengths:**
- 23 routes organized cleanly: public pages (/), auth pages (/login, /register), dashboard pages (/dashboard, /missions, /models, etc.), API routes (/api/*).
- Dynamic routes for detail pages (/missions/[missionId], /jobs/[id]).
- Grouped layouts where appropriate (dashboard/layout.tsx wraps auth guard).

**Issues:**

### [Low] Inconsistent layout strategy — AppShell not on all pages
- **Area:** Routing
- **Observation:** Most feature pages use AppShell directly; dashboard and jobs/[id] render standalone. This means either (a) no sidebar on dashboard/jobs, or (b) sidebar rendered differently.
- **Impact:** Users get inconsistent navigation experience across pages.
- **Recommendation:** Either wrap all authenticated pages in AppShell, or move AppShell to a root (authenticated) layout group.

---

## Mock Data Architecture — Score: 7/10

**Strengths:**
- Mock data is cleanly separated into `features/*/constants/mock.ts` files — never embedded in components.
- Types are implicit in mock data structures, making future schema migration straightforward.
- Dashboard and Mission Control mock data is comprehensive and realistic.

**Issues:**

### [Medium] No service layer abstraction between components and mock data
- **Area:** Mock Data
- **Observation:** Components directly import mock constants: `import { mockMetrics } from '@/features/dashboard/constants/mock'`. When APIs replace mocks, every import line must change.
- **Impact:** High refactoring cost during backend integration.
- **Recommendation:** Create service modules (`services/dashboardService.ts`) that currently return mock data but have the same interface as future API calls. Components import from services, not mock constants directly.

### [Low] Mock data not typed with shared interfaces
- **Area:** Mock Data
- **Observation:** Mock data objects are not explicitly typed with Pydantic-style or shared TypeScript interfaces. Types are inferred from the object shape.
- **Impact:** When API returns slightly different field names/casing, type mismatches will surface at runtime, not compile time.
- **Recommendation:** Define shared TypeScript interfaces in `types/` and type-assert mock data against them.

---

## Error Handling — Score: 4/10

**Strengths:**
- App-level error.tsx with "Try Again" button exists.
- Auth pages (login, register) handle form validation errors.
- API routes (feed, health, jobs, drift) have server-side error handling.

**Issues:**

### [High] No error boundaries on feature pages
- **Area:** Error Handling
- **Observation:** No page-level ErrorBoundary wrapping. A crash in any page section will cascade to the full page error state.
- **Impact:** A render error in the Activity Feed could hide the entire Mission Control UI.
- **Recommendation:** Wrap each major page section in an ErrorBoundary component.

### [High] jobs/[id] fetch has no error handling
- **Area:** Error Handling
- **Observation:** The fetch in jobs/[id] uses try/finally with no catch. Network errors or 500 responses silently resolve with undefined data.
- **Impact:** Users see a blank page with "Job not found" even when the job exists but the API errored — actively misleading.
- **Recommendation:** Add catch handler that sets an error state and renders an error card with retry button.

### [Medium] No error recovery patterns
- **Area:** Error Handling
- **Observation:** No page offers "Retry" after failure (except the app-level error.tsx). API polling in jobs/[id] silently stops if an error occurs.
- **Impact:** Users have no way to recover from transient errors without manual page refresh.
- **Recommendation:** Add retry logic to polling (exponential backoff, max 3 retries) and a visible "Connection lost — retrying" indicator.

---

## Architecture Score Summary

| Category | Score |
|---|---|
| Folder Structure | 8/10 |
| Component Architecture | 7/10 |
| Design System | 6/10 |
| Routing | 8/10 |
| State Management | 5/10 |
| Reusability | 7/10 |
| Performance Architecture | 6/10 |
| Accessibility Architecture | 4/10 |
| Scalability | 7/10 |
| Maintainability | 6/10 |

---

## Production Readiness

**Ready After Minor Refactoring** — The feature-first folder structure, path aliases, and CSS token system provide a strong architectural foundation. The main risks are: (1) dual design system between tokens.css and @theme, (2) missing state management abstraction for future API integration, (3) no error boundaries on feature pages. These are moderate-effort fixes with high impact on long-term maintainability.

---

## Long-Term Outlook

The architecture can support a team of 2-4 developers and ~50 pages without major restructuring. The feature-first organization, shared component library, and token system are the right foundations. Key architectural risks over 12-24 months:

1. **Token consolidation** — The CSS variable vs Tailwind @theme split will become increasingly painful as the team grows. Address now.
2. **Service layer missing** — Every new mock-data page increases backend integration cost. Establish the pattern before more pages are built.
3. **No testing strategy** — No unit tests on any component or page. This is acceptable for research/early stage but must be addressed before team expansion.
