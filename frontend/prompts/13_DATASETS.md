# 13_DATASETS.md

# Prometheus Swarm Frontend — Datasets

## Read First

Before beginning, read:

* 00_MASTER_PROMPT.md
* 01_PRODUCT_VISION.md
* 02_DESIGN_PRINCIPLES.md
* 03_INFORMATION_ARCHITECTURE.md
* 05_PAGE_SPECIFICATIONS.md
* 06_COMPONENT_LIBRARY.md
* 07_DESIGN_SYSTEM.md
* 08_MOTION_SYSTEM.md
* 09_MISSION_CONTROL.md
* 10_AGENT_EXPERIENCE.md
* 12_FRONTEND_ARCHITECTURE.md

Follow all project documentation.

---

# Objective

Build the complete Dataset Management experience.

Datasets are first-class engineering assets within Prometheus Swarm.

Users should be able to upload, inspect, organize, preview, compare, version, and understand every dataset used across projects and missions.

The experience should emphasize transparency, traceability, and readiness.

Use realistic mock data only.

---

# Scope

Frontend only.

Do NOT implement:

* File upload backend
* Dataset parsing
* Data processing
* Data validation backend
* AI analysis
* Storage APIs
* Database logic

Everything must be powered by mock data.

---

# Routes

Build:

```text
/datasets

/datasets/new

/datasets/[datasetId]

/datasets/compare
```

---

# Overall Experience

The Datasets section consists of:

```text
Datasets Dashboard

↓

Datasets Library

↓

Dataset Details

↓

Preview

↓

Statistics

↓

Version History

↓

Relationships

↓

Compare Datasets
```

---

# Dataset Dashboard

Display summary cards.

Examples:

* Total Datasets
* Ready for Training
* Processing
* Archived
* Recently Added
* Total Storage Used

Mock values only.

---

# Dataset Library

Support:

* Grid View
* List View

Each Dataset Card displays:

* Dataset Name
* Description
* Type
* Size
* Number of Samples
* Project
* Status
* Tags
* Last Updated
* Favorite

Hover actions:

* Open
* Duplicate (UI only)
* Archive (UI only)

---

# Search

Support searching by:

* Name
* Project
* Tags
* Type

Frontend only.

---

# Filters

Support filtering by:

* Type
* Status
* Project
* Tags
* Created Date
* Size

No backend filtering.

---

# Sorting

Options:

* Name
* Date Created
* Last Updated
* Size
* Sample Count

---

# Create Dataset

Create a dedicated page.

Support:

* Drag & Drop
* Browse Files
* Multiple Files
* Folder Upload (UI only)

Display upload queue with:

* Progress
* Status
* Remove
* Retry (mock)

No actual upload.

---

# Dataset Details

Layout:

```text
Header

↓

Overview

↓

Preview

↓

Statistics

↓

Relationships

↓

Version History

↓

Recent Activity
```

---

# Header

Display:

* Dataset Name
* Status
* Type
* Project
* Created Date
* Updated Date
* Owner

Actions:

* Upload New Version
* Download (UI only)
* Share (UI only)
* Favorite

---

# Overview

Display:

* Description
* Source
* Format
* Size
* Samples
* Classes (mock)
* Labels (mock)

Static values only.

---

# Dataset Preview

Automatically preview supported file types.

Support:

## CSV

Interactive table.

---

## JSON

Tree viewer.

---

## Images

Responsive image gallery.

---

## Text

Scrollable preview.

---

## Unknown Types

Metadata only.

No backend parsing.

---

# Statistics

Display reusable cards and charts.

Examples:

* Sample Count
* Class Distribution
* File Types
* Storage Usage
* Last Modified

Use mock charts.

---

# Relationships

Display connections to:

* Projects
* Missions
* Models
* Artifacts

Represent as relationship cards or simple graph.

---

# Version History

Display previous dataset versions.

Each Version Card includes:

* Version
* Created Date
* Author
* Summary

Allow switching between versions.

Frontend only.

---

# Recent Activity

Display timeline entries.

Examples:

* Uploaded
* Version Created
* Used in Training
* Linked to Project

Use mock data.

---

# Compare Datasets

Allow selecting two or more datasets.

Compare:

* Size
* Samples
* Type
* Format
* Classes
* Storage
* Created Date

Mock data only.

---

# Components to Build

Create reusable components:

* DatasetCard
* DatasetGrid
* DatasetTable
* DatasetHeader
* DatasetOverview
* DatasetPreview
* DatasetStatistics
* StatisticCard
* RelationshipPanel
* DatasetVersionHistory
* VersionCard
* DatasetActivityTimeline
* UploadQueue
* UploadItem
* DatasetComparisonTable

Reuse components whenever possible.

---

# Empty States

Provide empty states for:

* No datasets
* No preview available
* No versions
* No activity
* No search results

Guide the user toward the next action.

---

# Loading States

Create skeletons for:

* Dataset cards
* Statistics
* Preview
* Activity
* Version history

Reuse the shared Skeleton components.

---

# Motion

Implement subtle animations for:

* Card hover
* Upload queue
* Version selection
* Preview transitions
* Page navigation

Follow the Motion System.

---

# Accessibility

Ensure:

* Keyboard navigation
* Screen reader support
* Proper focus management
* Semantic HTML
* Accessible tables and charts

---

# Responsive Design

Desktop:

Multi-column layout.

Laptop:

Adaptive grids.

Tablet:

Single-column sections.

Maintain readability and usability.

---

# Mock Data

Store separately:

* Datasets
* Versions
* Statistics
* Activities
* Relationships
* Preview content
* Upload queue

Do not hardcode data inside components.

---

# Visual Style

The Datasets section should feel:

* Organized
* Professional
* Data-centric
* Trustworthy

Prioritize information hierarchy and readability over decorative effects.

---

# Deliverables

Provide:

## Pages Created

List all dataset pages.

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

Document assumptions, reusable patterns, and future backend integration points.

---

# Definition of Done

This task is complete only when:

* Dataset dashboard is implemented.
* Dataset library is complete.
* Create Dataset page is complete.
* Dataset detail page is complete.
* Preview system supports supported file types.
* Statistics section is implemented.
* Version history works with mock data.
* Compare Datasets page is implemented.
* Responsive behavior is complete.
* Theme support works.
* Accessibility requirements are met.
* No backend functionality has been implemented.
* No undocumented APIs have been introduced.

Stop after completing the Datasets experience.

Do not proceed to Training Dashboard or Deployment Center automatically.
