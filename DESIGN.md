---
name: UltiMaker Professional System
colors:
  surface: '#fcf9f8'
  surface-dim: '#F8F8F8'
  surface-bright: '#fcf9f8'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f2'
  surface-container: '#f0eded'
  surface-container-high: '#eae7e7'
  surface-container-highest: '#e4e2e1'
  on-surface: '#1b1c1c'
  on-surface-variant: '#454557'
  inverse-surface: '#303030'
  inverse-on-surface: '#f3f0ef'
  outline: '#767589'
  outline-variant: '#c6c4da'
  surface-tint: '#363cff'
  primary: '#0500af'
  on-primary: '#ffffff'
  primary-container: '#100aed'
  on-primary-container: '#acb0ff'
  inverse-primary: '#bfc2ff'
  secondary: '#006e27'
  on-secondary: '#ffffff'
  secondary-container: '#5cfd7b'
  on-secondary-container: '#007329'
  tertiary: '#735c00'
  on-tertiary: '#ffffff'
  tertiary-container: '#cea700'
  on-tertiary-container: '#4e3d00'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e0e0ff'
  primary-fixed-dim: '#bfc2ff'
  on-primary-fixed: '#02006e'
  on-primary-fixed-variant: '#0d04ec'
  secondary-fixed: '#6bff83'
  secondary-fixed-dim: '#3ce365'
  on-secondary-fixed: '#002107'
  on-secondary-fixed-variant: '#00531b'
  tertiary-fixed: '#ffe086'
  tertiary-fixed-dim: '#edc22a'
  on-tertiary-fixed: '#231b00'
  on-tertiary-fixed-variant: '#574500'
  background: '#fcf9f8'
  on-background: '#1b1c1c'
  surface-variant: '#e4e2e1'
  danger-primary: '#FF0021'
  danger-hover: '#CC001A'
  danger-active: '#990014'
  danger-surface: '#FFE6E9'
  warning-light: '#FFF8D9'
  text-secondary: '#707070'
  disabled: '#8D8D8D'
  accent-surface: '#E7E7FD'
typography:
  display-progress:
    fontFamily: Noto Sans
    fontSize: 36px
    fontWeight: '600'
    lineHeight: 40px
  headline-sm:
    fontFamily: ibmPlexSans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  action-lg:
    fontFamily: Messina Sans
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 22px
  action-md:
    fontFamily: Messina Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 18px
  body-md:
    fontFamily: ibmPlexSans
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  body-sm:
    fontFamily: ibmPlexSans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  technical-md:
    fontFamily: ibmPlexMono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
  technical-sm:
    fontFamily: ibmPlexMono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 18px
  indicator-bold:
    fontFamily: Messina Sans
    fontSize: 12px
    fontWeight: '660'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
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

The design system is engineered for industrial precision and technical reliability. It targets a professional audience of engineers, designers, and fleet managers who require high data density and functional clarity. 

The aesthetic is **Corporate / Modern** with a lean towards **Functional Minimalism**. It avoids decorative flourishes, instead utilizing a strict 8px grid, high-contrast color application for status signaling, and a completely flat depth model. The visual tone is authoritative and systematic, ensuring that hardware status and complex print configurations remain the primary focus.

## Colors

The color palette is functionally driven, using high-saturation primary and status colors against a stark neutral background.

- **Primary Blue (#100AED)**: Reserved for primary actions, branding, and active interactive states.
- **Success Green (#00C84E)**: Indicates 'Available' or 'Complete' states.
- **Danger Red (#FF0021)**: Used for destructive actions and 'Error' states. It features a deep ramp for interaction (Hover: #CC001A, Active: #990014).
- **Attention Yellow (#FDD13A)**: Used for 'Warning' or 'Action Required' badges.
- **Neutrals**: `#282828` serves as the primary text color for maximum legibility. `#F8F8F8` is the standard surface for low-priority backgrounds and disabled states.

## Typography

This design system uses a multi-font strategy to differentiate between interface actions, content, and technical data.

- **Messina Sans**: Used for buttons and navigational actions to provide a modern, distinct feel.
- **IBM Plex Sans**: The primary typeface for all UI labels, body text, and headings, chosen for its industrial legibility.
- **IBM Plex Mono**: Used for helper text, technical values, and metadata to emphasize the "machine" nature of the data.
- **Noto Sans**: Reserved exclusively for large display values, such as print progress percentages.

## Layout & Spacing

The layout follows a **Fixed Grid** philosophy based on an 8px square rhythm.

- **Vertical Rhythm**: All interactive components adhere to fixed height increments: 32px (Small), 40px (Medium), and 48px (Large). 
- **Internal Spacing**: Use 8px for standard gaps between icons and text. Use 4px for tight clusters (e.g., badges or small input details).
- **Margins & Gutters**: Standard page margins are 24px, with 16px gutters between major layout cards. 
- **Mobile Reflow**: On mobile devices, 48px components are preferred for touch targets. Horizontal section padding reduces from 24px to 16px.

## Elevation & Depth

This design system is **strictly flat**. It does not use shadows to convey depth. Hierarchy is established through:

- **Tonal Layering**: Secondary information or containers use `#F8F8F8` surfaces against the main `#FFFFFF` background.
- **High-Contrast Fills**: Primary actions and critical statuses use solid, saturated fills to draw the eye immediately.
- **Borders**: Interactive elements (like outlined buttons or input fields) use 1px solid borders to define boundaries. 
- **Dimming**: Disabled states use a combination of `#8D8D8D` text and `#F8F8F8` fills to "push" content into the background.

## Shapes

The shape language is conservative and professional. 

- **Standard Radius**: 4px is applied to all buttons, input fields, and status badges to provide a "softened technical" look.
- **Container Radius**: 8px is used for larger surfaces like cards and desktop navigation menus to create visual distinction from smaller components.
- **Pill Shape**: Full rounding (1000px) is reserved exclusively for "Status Badges" and "Tertiary Round Buttons" to make them instantly recognizable as distinct from standard UI controls.

## Components

### Buttons
- **Primary**: Filled `#100AED` with White text. 4px radius.
- **Secondary (Outlined)**: 1px border matching text color. Default uses Primary Blue; Danger uses `#FF0021`.
- **Ghost**: No fill or border. Used for low-priority actions.
- **Sizes**: Small (32px), Medium (40px), Large (48px).

### Status Indicators
- **Printing**: Uses Primary Blue with a 'Play' or 'Loading' icon.
- **Available**: Uses Success Green (#00C84E).
- **Warning**: Uses Attention Yellow (#FDD13A) background with Neutral Dark text.
- **Error**: Uses Danger Red (#FF0021) background or text.

### Inputs
- **Text Fields**: 32px or 40px height. 1px border. Labels use `IBM Plex Sans` (12px Regular). 
- **Dropdowns**: Feature a `Chevron--down` icon (16px) aligned to the right.

### Cards
- Use an 8px radius with a 1px border or a `#F8F8F8` fill. Padding is typically 16px or 24px depending on the content density.

### Progress Patterns
- Quantitative monitoring components must use `Noto Sans` for the primary value and `IBM Plex Mono` for the units/labels to ensure high-impact technical clarity.

---

## Companion Guides

For detailed layout principles, SCSS module standards, and WCAG accessibility requirements, refer to:
- **[SCSS Layout Guide (scss-layout-guide.md)](scss-layout-guide.md)**
- **[Accessibility Guide (accessibility-guide.md)](accessibility-guide.md)**
- **[Agent Onboarding Guide (AGENTS.md)](AGENTS.md)**