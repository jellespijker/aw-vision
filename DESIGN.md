---
name: aw-vision Premium System
colors:
  surface: '#0f172a'
  surface-dim: '#020617'
  surface-bright: '#1e293b'
  surface-container-lowest: '#0f172a'
  surface-container-low: '#1e293b'
  surface-container: '#1e293b'
  surface-container-high: '#334155'
  surface-container-highest: '#475569'
  on-surface: '#f8fafc'
  on-surface-variant: '#94a3b8'
  outline: '#475569'
  outline-variant: '#334155'
  primary: '#3b82f6'
  on-primary: '#ffffff'
  primary-container: '#1e3a8a'
  on-primary-container: '#93c5fd'
  secondary: '#10b981'
  on-secondary: '#ffffff'
  secondary-container: '#064e3b'
  on-secondary-container: '#a7f3d0'
  error: '#ef4444'
  on-error: '#ffffff'
  error-container: '#7f1d1d'
  on-error-container: '#fca5a5'
  warning: '#f59e0b'
  on-warning: '#000000'
  warning-container: '#78350f'
  on-warning-container: '#fde68a'
typography:
  display-progress:
    fontFamily: Outfit, Inter, sans-serif
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 38px
  headline-lg:
    fontFamily: Outfit, Inter, sans-serif
    fontSize: 28px
    fontWeight: '700'
    lineHeight: 34px
  headline-md:
    fontFamily: Outfit, Inter, sans-serif
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 26px
  body-md:
    fontFamily: Inter, Roboto, sans-serif
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: Inter, Roboto, sans-serif
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  technical-md:
    fontFamily: Fira Code, JetBrains Mono, monospace
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  technical-sm:
    fontFamily: Fira Code, JetBrains Mono, monospace
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 16px
rounded:
  sm: 4px
  DEFAULT: 6px
  md: 8px
  lg: 12px
  xl: 16px
  full: 9999px
spacing:
  base: 8px
  sub: 4px
  tight: 2px
  md: 12px
  lg: 16px
  xl: 24px
  h-sm: 32px
  h-md: 40px
  h-lg: 48px
---

## Brand & Style

The design system for `aw-vision` is engineered for technical precision, data-rich clarity, and futuristic appeal. It is designed specifically for power users, developers, and productivity engineers who want a modern **dark-theme dashboard** that feels alive, interactive, and visually stunning.

The design philosophy is **Premium Glassmorphic Dark-Mode**. It uses dark backgrounds, semi-transparent cards with fine borders, vibrant neon color accents for status signaling, smooth micro-animations (pulse points), and beautiful color gradients. It avoids flat or clinical styling, making search and recollection feel premium.

---

## Colors

The color palette is built around high-contrast neon status signals over deeply dark, cohesive surfaces.

* **Background Dark (#0F172A)**: The foundational backdrop surface.
* **Surface Bright (#1E293B)**: Used for main component cards, navigation areas, and text blocks to create layered contrast.
* **Premium Brand Gradient (Blue to Purple)**: A smooth linear gradient transitioning from `rgba(59,130,246,1)` to `rgba(139,92,246,1)`. Reserved for primary header text gradients, highlighting primary actions, and hero sections.
* **Interactive Primary Blue (#3B82F6)**: Used for buttons, interactive outlines, input focuses, and highlighted text.
* **Success Green (#10B981)**: Indicates active and operational states (e.g., active deamons, complete processing).
* **Warning Yellow (#F59E0B)**: Highlights issues requiring intervention, such as offline servers or pending items.
* **Danger Red (#EF4444)**: Indicates errors, empty states, or stopped daemons.
* **Neutrals**: `#F8FAFC` represents primary, high-contrast typography. `#94A3B8` represents secondary muted text labels.

---

## Typography

A dual-font approach is enforced to differentiate between editorial headers, general interface content, and technical machine records:

* **Outfit / Outfit-inspired (Google Fonts)**: Used for display numbers, main page headers, and tab selectors to present a sleek, technical-architectural vibe.
* **Inter**: The main workhorse typeface for UI labels, lists, metadata, and body text. Chosen for high readability on low-contrast backdrops.
* **Fira Code / JetBrains Mono**: Employed for raw OCR dumps, system logs, code snippets, database paths, and model identifiers to emphasize raw machine-processed telemetry.

---

## Layout & Spacing

* **8px Square Grid**: All components align to an 8px architectural rhythm.
* **Heights**: Inputs and primary actions default to standard heights: 32px (Small), 40px (Medium), and 48px (Large).
* **Grid Layouts**: Dashboard lists and libraries use a multi-column responsive flex grid with 24px spacing (`gap-4` / `mb-4`) to support seamless reflows across Viewport boundaries.

---

## Elevation, Depth & Glassmorphism

Hierarchy is defined through light values, fine borders, and backdrop filtering rather than heavy box shadows:

* **Borders**: Component borders use a thin `1px solid rgba(255,255,255,0.08)` to clearly bound cards without adding visual clutter.
* **Backdrop Blur**: Modals, chats, and image cards employ glassmorphism:
  ```css
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  ```
* **Active Overlays**: Hovering over interactive tiles triggers smooth scaling (`transform: translateY(-4px)`) and slightly increases border opacity to reflect responsive hover states.

---

## Shapes & Radius

* **Card Radius (16px / `rounded-xl`)**: Applied to all main gallery cards, chat modules, and status displays to create a softened, modern appearance.
* **Input Radius (50px / `rounded-pill`)**: Reserved for search inputs and conversational prompt boxes to support fluid, flowing user entries.
* **Badge Radius (9999px / `badge-pill`)**: Employed on status chips and queue indicators.

---

## Premium Custom Components

### 1. Status Indicator Pulse Dot
A custom animated dot indicating background processing and daemon health:
* **Success (Active)**: A green center `#10B981` with an outer ring scale animation that fades out:
  ```css
  box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
  animation: pulse 2s infinite;
  ```
* **Danger (Stopped)**: A red center `#EF4444`.

### 2. Glassmorphic Archived Placeholder Card
Renders in place of raw screenshots older than 14 days that have been purged by the retention daemon:
* **Background**: Stark linear gradient from `#1E293B` to `#0F172A`.
* **Visuals**: A prominent archive cabinet icon (`archive`) centered with a semi-transparent opacity (`0.5`).
* **Text**: Small, highly stylized tag reading: `Archived Metadata (Screenshot purged to save space)`. It retains all metadata, tags, and searchable text, ensuring zero loss of semantic recollection capacity.

### 3. Collapsible Monospaced OCR Panel
A specialized panel used on gallery cards and detail lightboxes to display extracted raw desktop text:
* **Design**: Encased in a solid background `#0F172A` with a 1px border.
* **Typography**: Leverages `Fira Code` with small font scaling (`0.85em`).
* **Interaction**: Collapsed by default. Clicking the `file-alt` toggle slides the panel open with a CSS transition, exposing the raw text with a copy-to-clipboard button.

### 4. Interactive Chat Conversation Interface
* **User Bubbles**: Aligned right, styled with a solid primary background `#3B82F6` and white text.
* **Agent Bubbles**: Aligned left, styled with a glassmorphic surface `#1E293B`, featuring fine borders, rendering markdown responses with clean spacing.
* **Thinking State**: A customized horizontal group of bouncing dots showing active background tool execution.
