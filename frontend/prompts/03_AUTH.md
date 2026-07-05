# 04_AUTHENTICATION.md

# Prometheus Swarm Frontend — Authentication

## Read First

Before starting, carefully read:

* 00_MASTER_PROMPT.md
* 01_PRODUCT_VISION.md
* 02_DESIGN_PRINCIPLES.md
* 04_USER_FLOWS.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 12_FRONTEND_ARCHITECTURE.md

These documents define the expected behavior and appearance.

---

# Objective

Build the complete frontend authentication experience for Prometheus Swarm.

This includes only the user interface, routing, validation, transitions, and state handling required on the frontend.

Do **NOT** implement backend authentication.

---

# Scope

Frontend only.

Never create:

* Authentication APIs
* JWT generation
* Session management implementation
* Password hashing
* Database models
* OAuth backend logic
* User persistence

Treat authentication services as existing external services.

Use mock responses where needed.

---

# Pages to Build

Implement the following pages:

* Login
* Register
* Forgot Password
* Reset Password
* Verify Email
* Authentication Loading Screen

All pages should share the same visual identity.

---

# Design Goals

The authentication experience should feel:

* Premium
* Minimal
* Fast
* Professional
* Calm
* Trustworthy

Inspired by:

* Claude
* Linear
* Vercel

Do not copy any existing interface.

---

# Authentication Layout

Create a reusable authentication layout.

Structure:

```text
┌────────────────────────────────────────────┐
│                Brand Logo                  │
│                                            │
│          Authentication Card               │
│                                            │
│      Login / Register / Reset Form         │
│                                            │
│          Supporting Information            │
└────────────────────────────────────────────┘
```

The layout should be centered and responsive.

---

# Login Page

Include:

* Email input
* Password input
* Show / Hide password
* Remember me checkbox
* Forgot password link
* Login button
* Register link

Validation should be handled entirely on the frontend.

No backend calls.

---

# Register Page

Include:

* Full Name
* Email
* Password
* Confirm Password
* Password strength indicator
* Terms acceptance checkbox
* Register button
* Login link

Display inline validation messages.

---

# Forgot Password

Include:

* Email field
* Continue button
* Success confirmation screen

Mock successful submission.

---

# Reset Password

Include:

* New Password
* Confirm Password
* Password strength
* Reset button

Mock success.

---

# Verify Email

Design a verification screen containing:

* Success illustration
* Status message
* Resend email button
* Continue button

No backend implementation.

---

# Form Components

Reuse the Design System.

Support:

* Labels
* Helper text
* Error messages
* Disabled state
* Loading state
* Success state

---

# Validation

Use:

* React Hook Form
* Zod

Validate:

* Email format
* Password length
* Password confirmation
* Required fields

Never rely solely on HTML validation.

---

# Password Strength

Implement a frontend-only strength indicator.

Evaluate:

* Length
* Uppercase
* Lowercase
* Numbers
* Symbols

Display visual feedback only.

---

# Loading States

Create polished loading states for:

* Form submission
* Verification
* Redirect

Use skeletons or subtle animations.

---

# Error States

Create reusable error displays for:

* Invalid credentials
* Weak password
* Network unavailable (mock)
* Unknown error

Use mock scenarios only.

---

# Success States

Create reusable success feedback for:

* Registration complete
* Password reset
* Email sent
* Verification complete

---

# Motion

Follow the Motion System.

Animate:

* Form transitions
* Input focus
* Validation feedback
* Button loading
* Page transitions

Animations should be subtle and purposeful.

---

# Accessibility

Support:

* Keyboard navigation
* Proper labels
* ARIA attributes
* Screen readers
* Visible focus states
* High contrast

Meet WCAG best practices.

---

# Responsive Design

Support:

* Desktop
* Laptop
* Tablet

Forms should remain readable and usable on smaller screens.

---

# Mock Authentication Service

Create a temporary frontend service that returns mock responses.

Requirements:

* Simulate loading
* Simulate success
* Simulate failure

Do not implement real authentication.

Keep the service isolated so it can later be replaced with real backend integration.

---

# Route Protection

Create placeholder route guards.

Behavior:

* If "authenticated" (mock state), navigate to Dashboard.
* Otherwise, stay on authentication pages.

Do not implement real session logic.

---

# Deliverables

Provide:

## Pages Created

List all authentication pages.

---

## Components Created

List reusable authentication components.

---

## Validation Rules

Summarize implemented validation.

---

## Files Created

List all created files.

---

## Files Modified

List modified files.

---

## Mock Services

Describe temporary mock authentication services.

---

## Notes

Document assumptions and integration points.

---

# Definition of Done

This task is complete only when:

* All authentication pages exist.
* Forms validate correctly.
* Password strength works.
* Loading, success, and error states are implemented.
* Mock authentication flow is functional.
* Components follow the design system.
* Accessibility requirements are satisfied.
* Responsive layouts are complete.
* No backend code has been created.
* The frontend is ready to connect to a real authentication service in the future.

Stop after completing the authentication experience.

Do not continue to the Dashboard or any other feature automatically.
