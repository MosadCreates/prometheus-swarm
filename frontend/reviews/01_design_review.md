# 01_DESIGN_REVIEW.md

# Prometheus Swarm Frontend — Design Review

## Objective

Design review completed on 2026-07-04.

---

# Review Findings

## Product Identity — Score: 7/10

**Strengths:**
- The Agent Fleet panel (Scout, Forge, Furnace, Dissect, Arbiter, Harbor) establishes a unique identity vs generic AI chat apps. Each agent has a distinct color, role, and visual token.
- The cool-tone design system (blue/indigo/green) with Inter typography feels professional and engineering-oriented.
- Mission Control's three-panel layout communicates "operational dashboard" rather than "chat interface" — correct differentiation.
- The landing page hero ("You describe the task. The swarm does the rest.") clearly communicates the product's unique value.

**Issues:**

### [Medium] Dual design language — warm landing + cool dashboard
- **Category:** Visual
- **Problem:** Landing page uses a warm tone system (#C96442 copper accent, #F7F6F3 warm bg), while dashboard pages use cool tones (#2563eb blue, #f9fafb cool bg). These look like two different products.
- **Why It Matters:** Users navigating from landing → dashboard experience a jarring visual discontinuity. This erodes trust in the product's polish.
- **Recommendation:** Unify on one color system. Either warm the dashboard or cool the landing page consistently.

### [Low] Six agent colors lack functional differentiation
- **Category:** Visual
- **Problem:** Agent colors (blue, purple, red, green, amber, cyan) are visually distinct but some pairings (Scout blue vs Forge purple in dark mode) reduce contrast against dark backgrounds.
- **Why It Matters:** Users scanning the activity feed need to quickly identify which agent is active. Low contrast reduces scan speed.
- **Recommendation:** Add secondary differentiators (icons, shapes, or positions) so agent identification works even when color perception is limited.

---

## Visual Hierarchy — Score: 7/10

**Strengths:**
- Mission Control has clear 3-zone layout with consistent heading hierarchy (h1 → h2 → h3 → h4).
- Dashboard metric cards have good visual weight with large numbers, subtle labels, and icons.
- Sidebar uses icon + text labels, active state highlighting, and collapsible mode — strong navigation hierarchy.

**Issues:**

### [Medium] Timeline stages have weak visual differentiation
- **Category:** Visual
- **Problem:** The 8-stage timeline uses numbered circles with color changes (completed=green, active=blue, pending=gray). On dark mode, the gray pending stages nearly disappear against the dark surface background.
- **Why It Matters:** Users cannot quickly assess "how far along" the mission is without close inspection.
- **Recommendation:** Increase circle size, add connecting line animation for completed stages, and use more contrasting pending-stage colors.

### [Low] Activity feed events lack visual weight hierarchy
- **Category:** Visual
- **Problem:** All activity events have identical styling regardless of importance. A completed EDA step looks the same as a crash event.
- **Why It Matters:** Critical events (errors, failures) can be missed in a long feed of routine events.
- **Recommendation:** Introduce severity-based styling — warning/error events get amber/red left borders or background tinting.

---

## Layout — Score: 8/10

**Strengths:**
- Mission Control's three-panel layout with resizable affordances is clean and well-proportioned.
- Dashboard's 4-column metric grid → 2-column middle section → 3-column bottom section creates visual variety without clutter.
- Mission Composer's three-panel layout mirrors Mission Control — good consistency.

**Issues:**

### [High] No responsive layout — desktop only
- **Category:** Layout
- **Problem:** Side panels use fixed widths (w-60=240px, w-72=288px) with shrink-0, providing no responsiveness. Below ~1100px viewport width, the layout overflows horizontally.
- **Why It Matters:** ~15% of professional users work on laptops with 1280-1366px screens. On a 1280px display, the center panel gets only ~380px — extremely cramped.
- **Recommendation:** Implement collapsible panels at the `xl` breakpoint, with panel toggle buttons in the header.

### [Low] AppShell sidebar and standalone pages use different layouts
- **Category:** Layout
- **Problem:** Dashboard and jobs/[id] do not use AppShell, creating two visual layout modes. Users navigating between /dashboard and /missions see different chrome.
- **Why It Matters:** Inconsistent chrome reduces spatial consistency and user confidence.
- **Recommendation:** Standardize all authenticated pages to use AppShell.

---

## Navigation — Score: 7/10

**Strengths:**
- Sidebar has 8 primary nav items with icon+label and active state highlighting.
- Collapsible sidebar with icon-only mode is space-efficient.
- Mission detail pages have back-arrow navigation.

**Issues:**

### [Medium] No breadcrumbs on detail pages
- **Category:** Navigation
- **Problem:** Mission Control (/missions/[id]) and New Mission (/missions/new) have no breadcrumb trail showing "Missions > Current Mission".
- **Why It Matters:** Users navigating deep into the app lose spatial awareness of where they are.
- **Recommendation:** Add breadcrumb component to all detail-level pages.

### [Low] No global command palette or search
- **Category:** Navigation
- **Problem:** The sidebar shows a search button with a keyboard shortcut hint (⌘K) but no implementation.
- **Why It Matters:** As the app scales to dozens of pages and hundreds of missions, keyboard-powered navigation becomes essential for power users.
- **Recommendation:** Implement ⌘K command palette with mission search, page navigation, and quick actions.

---

## User Experience — Score: 7/10

**Strengths:**
- Mission Composer → Mission Control pipeline provides a coherent "create → monitor" workflow.
- Empty states (6 pages) have helpful icons, messages, and CTAs — good onboarding for new users.
- Keyboard shortcut hints on Launch (`Enter`) and New Mission (`N`) buttons show attention to power users.

**Issues:**

### [High] No loading states on mock-data pages
- **Category:** UX
- **Problem:** Dashboard, Mission Composer, and Mission Control have zero loading states because they use synchronous mock data. When real APIs replace mocks, users will see blank screens during data fetches.
- **Why It Matters:** Users confronting blank screens will refresh or leave, assuming the application is broken.
- **Recommendation:** Add skeleton loading states to every page section, pre-wired to mock data timing but ready for API integration.

### [High] No error states on any page except jobs/[id]
- **Category:** UX
- **Problem:** If mock data fails to load (or when real API errors occur), no page shows an error state. The user gets empty sections with no explanation.
- **Why It Matters:** Silent failures destroy user trust. Users need to know when something went wrong and what to do about it.
- **Recommendation:** Add error boundary to each page section with retry buttons.

### [Medium] Settings page is entirely placeholder
- **Category:** UX
- **Problem:** Settings shows "Account settings will be available soon" for all 5 sections (Account, Notifications, Theme, API Keys, Security). Theme toggle already exists in NavUserMenu but is not reflected in Settings.
- **Why It Matters:** Users expect settings to work. A "coming soon" page in a product otherwise built-out signals incompleteness.
- **Recommendation:** Implement Theme toggle in Settings (mirroring NavUserMenu). Populate Account with profile fields.

---

## Motion — Score: 4/10

**Strengths:**
- AgentDrawer has a nice slide-in-right animation (0.2s ease-out).
- Progress bars animate width changes smoothly (500ms transition).

**Issues:**

### [Critical] No prefers-reduced-motion support anywhere
- **Category:** Motion
- **Problem:** All animations (AgentDrawer slide-in, pulse on running agents, progress bar transitions, hover effects) fire regardless of the user's `prefers-reduced-motion: reduce` OS setting.
- **Why It Matters:** Users with vestibular disorders may experience discomfort or nausea from unexpected motion. This violates WCAG 2.2 Success Criterion 2.3.3.
- **Recommendation:** Wrap all animations in `@media (prefers-reduced-motion: no-preference)` or use Tailwind's `motion-safe:` prefix. Disable the AgentDrawer slide-in when reduced motion is preferred.

### [Medium] Dialog has no enter/exit animation
- **Category:** Motion
- **Problem:** The shared Dialog component appears/disappears instantly. Mission Composer's LaunchDialog has the same issue.
- **Why It Matters:** Instant appearance/disappearance feels jarring and unpolished compared to the rest of the 200ms-transition system.
- **Recommendation:** Add fade-in + scale-up on open, fade-out on close, matching the `--duration-normal` token (200ms).

### [Low] No micro-interactions on interactive elements
- **Category:** Motion
- **Problem:** Buttons have hover state transitions but no press (active) state animation. Agent cards have hover effects but no active/tap state.
- **Why It Matters:** Micro-interactions communicate responsiveness. Their absence makes the UI feel slightly "dead" compared to polished products like Linear or Vercel.
- **Recommendation:** Add subtle scale(0.98) on button press and active state transitions on cards.

---

## Theme — Score: 6/10

**Strengths:**
- Full dark mode with carefully chosen per-token overrides (brighter accents on dark, deeper shadows).
- Theme persistence via localStorage with system preference detection.
- Agent colors remain consistent across themes.

**Issues:**

### [High] jobs/[id] page completely ignores design tokens
- **Category:** Theme
- **Problem:** `/jobs/[id]` uses hardcoded hex colors throughout (#E8E5DF, #C96442, #1C1B19, #F7F6F3, etc.). This page will not respond to theme changes and looks wrong in dark mode.
- **Why It Matters:** This is the most functionally complete page (live data from Redis, polling, copy-to-clipboard). It defaults to light-mode colors even in dark mode, breaking the experience for dark-mode users.
- **Recommendation:** Refactor all hex colors in jobs/[id] to `var(--color-*)` tokens and test in both themes.

### [Medium] Hardcoded warm values in layout.tsx and globals.css
- **Category:** Theme
- **Problem:** The root layout.tsx uses `bg-[#F7F6F3]/80`, `text-[#1C1B19]`, `border-[#E8E5DF]`, `bg-[#C96442]` — all hardcoded warm colors. globals.css has similar hardcoded `.btn-accent` styles.
- **Why It Matters:** These landing-page elements bypass the design system and won't adapt to theme changes.
- **Recommendation:** Replace with `var(--color-bg)`, `var(--color-text-primary)`, `var(--color-border)`, `var(--color-primary)` or define warm-landing-page-specific tokens.

### [Low] Token duplication between tokens.css and @theme
- **Category:** Theme
- **Problem:** Agent colors and status colors are defined identically in both tokens.css (`:root`) and globals.css (`@theme`). This creates a maintenance hazard — updating one without the other will cause inconsistency.
- **Why It Matters:** Future developers may update one source and miss the other, creating hard-to-debug visual inconsistencies.
- **Recommendation:** Choose one source of truth. Either use pure CSS variables referenced by `var(--*)` everywhere, or use `@theme` exclusively and migrate all code to Tailwind utility classes.

---

## Responsiveness — Score: 3/10

**Strengths:**
- Dashboard grid uses responsive breakpoints (`grid-cols-1 lg:grid-cols-2 xl:grid-cols-4`).
- Mission Composer hides side panels on mobile (`hidden lg:block`).

**Issues:**

### [Critical] Mission Control is unusable below ~1100px
- **Category:** Layout
- **Problem:** Fixed-width panels (240px left + 288px right = 528px) plus sidebar (240px) total 768px of chrome before any content. The center panel is squeezed to near-zero on tablets.
- **Why It Matters:** Users on laptops or tablets cannot effectively use the product's core experience.
- **Recommendation:** Collapse side panels into slide-out drawers at `xl` breakpoint. Make the center panel always visible.

### [Medium] No tablet or mobile navigation strategy
- **Category:** Layout
- **Problem:** The sidebar has no hamburger menu or mobile drawer. On small screens, the sidebar overlays the main content.
- **Why It Matters:** Tablet users (iPad Pro 12.9" = 1024px) cannot navigate the app.
- **Recommendation:** Add a hamburger-triggered mobile drawer for the sidebar at the `lg` breakpoint.

---

## Overall Score

| Category | Score |
|---|---|
| Visual Design | 7/10 |
| UX | 7/10 |
| Accessibility | 4/10 |
| Responsiveness | 3/10 |
| Consistency | 6/10 |
| Scalability | 6/10 |
| Product Identity | 7/10 |
| Theme | 6/10 |
| Motion | 4/10 |
| Overall Readiness | 6/10 |

---

## Final Verdict

**Ready after Minor Improvements** — The product identity is strong and differentiated from generic AI chat. Mission Control's three-panel layout and the six-agent color system communicate transparency and engineering professionalism. However, responsive layout, motion safety, theme token consistency for jobs/[id], and error/loading state coverage must be resolved before production. The design system foundation (tokens.css, dark mode, shared components) is excellent and shows world-class attention to detail.

---

## Top 5 Priorities

1. **Add `prefers-reduced-motion` respect** — affects WCAG compliance and user safety
2. **Fix jobs/[id] hardcoded colors** — breaks dark mode for the most-used functional page
3. **Add loading/error/empty states to all mock-data pages** — prevents blank-screen failure mode
4. **Implement responsive layout for Mission Control** — core experience unusable below 1100px
5. **Unify dual design system** — warm landing vs cool dashboard creates product identity confusion
