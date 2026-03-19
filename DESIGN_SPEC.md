# youtube-model-feeder — Design Specification & Component Library
**Project:** YouTube Tutorial to Markdown Converter
**Created:** 2026-02-28
**Design System:** Multi-Theme (Monokai default, Lunaris, Nord)
**Version:** 1.0

> **Note:** The color palette and typography in this spec (indigo primary, Fraunces/DM Sans) reflect the original design intent. The live implementation uses the Monokai/Lunaris/Nord token system defined in `frontend/app/globals.css` and `frontend/lib/themes.ts`. Refer to those files for current token values.

---

## 📋 Table of Contents
1. [Overview](#overview)
2. [Design System](#design-system)
3. [Color Palette](#color-palette)
4. [Typography](#typography)
5. [Spacing & Layout](#spacing--layout)
6. [Components](#components)
7. [Screen Designs](#screen-designs)
8. [Mobile Responsive](#mobile-responsive)
9. [States & Variations](#states--variations)
10. [Implementation Guide](#implementation-guide)

---

## Overview

This design specification covers the complete UI/UX design for **youtube-model-feeder**, a web application that converts YouTube tutorials into searchable markdown documents with snapshots and AI-powered summaries.

**Key Features:**
- YouTube video processing (transcript extraction, snapshot generation)
- User authentication and account management
- LLM provider selection (Ollama, OpenAI, Anthropic)
- VS Code-like workspace for document editing
- Document dashboard with export options

---

## Design System

### Core Philosophy
- **Developer-Focused:** Clean, efficient interface reminiscent of developer tools
- **Dark-First:** Premium dark mode with high contrast for reduced eye strain
- **Accessible:** WCAG AA compliant, semantic color usage
- **Responsive:** Desktop-first, mobile-optimized views

### Design Tokens

#### Color System

| Role | Color | Hex | Usage |
|------|-------|-----|-------|
| **Primary Background** | Deep Charcoal | `#0B0B0E` | Main page background |
| **Secondary Background** | Elevated Dark | `#16161A` | Headers, panels |
| **Tertiary Background** | Interactive Dark | `#1A1A1E` | Inputs, buttons (secondary) |
| **Text Primary** | Near White | `#FAFAF9` | Headlines, primary text |
| **Text Secondary** | Gray | `#6B6B70` | Labels, descriptions |
| **Text Tertiary** | Muted Gray | `#4A4A50` | Placeholders, disabled |
| **Border Subtle** | Dark Border | `#2A2A2E` | Dividers, subtle strokes |
| **Border Strong** | Emphasized Border | `#3A3A40` | Input focus, emphasized borders |
| **Accent Primary (Green)** | Emerald | `#32D583` | Success, completion, active states |
| **Accent Secondary (Indigo)** | Primary Action | `#6366F1` | CTAs, primary buttons, focus |
| **Accent Tertiary (Coral)** | In-Progress | `#E85A4F` | Processing, warnings, secondary CTAs |
| **Accent Warning (Amber)** | Warning | `#FFB547` | Warnings, partial states |

#### Color Usage Rules
- **Success States:** Emerald (#32D583)
- **Processing States:** Coral (#E85A4F)
- **Error States:** Coral (#E85A4F) with text emphasis
- **Information States:** Indigo (#6366F1)
- **Warning States:** Amber (#FFB547)

---

## Typography

### Font Families

| Family | Weight | Usage | Notes |
|--------|--------|-------|-------|
| **Fraunces** | 500–700 | Headlines, page titles, section headers | Serif, editorial authority |
| **DM Sans** | 400–700 | Navigation, buttons, labels, body | Geometric sans-serif, functional |
| **Monospace** | 400–600 | Code snippets, logs, technical content | System monospace font |

### Type Scale

| Size | Font | Weight | Letter Spacing | Usage |
|------|------|--------|-----------------|-------|
| 36px | DM Sans | 700 | -1.2px | Large metric values |
| 28px | Fraunces | 600 | -0.8px | Page title |
| 24px | Fraunces | 600 | -0.5px | Section title (desktop) |
| 18px | Fraunces | 600 | -0.3px | Subsection title |
| 16px | DM Sans | 600 | 0 | Headline, body text, button text |
| 14px | DM Sans | 600 | 0 | Label, callout text |
| 13px | DM Sans | 500 | 0 | Body text, description |
| 12px | DM Sans | 500 | 0 | Footnote, caption |
| 11px | DM Sans | 600 | 0 | Badge text |

### Line Height
- **Headlines:** 1.2 (tight)
- **Body Text:** 1.5 (readable)
- **Labels:** 1.3 (standard)

---

## Spacing & Layout

### Gap Scale (between elements)
```
24px — Section spacing (major sections)
16px — Card/Container spacing
14px — Row spacing (list items)
12px — Medium spacing (internal cards)
8px  — Standard spacing (icon + label)
6px  — Small spacing (components)
4px  — Tight spacing (minimal)
2px  — Minimal spacing
```

### Padding Scale

| Context | Horizontal | Vertical | Usage |
|---------|------------|----------|-------|
| Page | 80px | 48px | Desktop page padding |
| Card | 20px | 20px | Standard card padding |
| Button | 16px | 12px | Button internal padding |
| Input | 14px | 12px | Input field padding |
| Badge | 12px | 8px | Badge padding |

### Layout System
- **Max Container Width:** 1440px (desktop)
- **Mobile Width:** 390px (iPhone 14 standard)
- **Grid Columns:** 12-column, 16px gutter
- **Default Gap:** 24px (sections), 16px (containers)

---

## Components

### Buttons

#### Primary Button
- **Background:** Indigo (#6366F1)
- **Text Color:** White (#FFFFFF)
- **Padding:** 16px horizontal, 12px vertical
- **Height:** 48px
- **Border Radius:** 8px
- **Font:** DM Sans 14px 600
- **States:**
  - Default: Full opacity
  - Hover: Opacity 90%
  - Active: Opacity 80%
  - Disabled: Opacity 50%

#### Secondary Button
- **Background:** Interactive Dark (#1A1A1E)
- **Border:** 1px solid Border Subtle (#2A2A2E)
- **Text Color:** Near White (#FAFAF9)
- **Padding:** 16px horizontal, 12px vertical
- **Height:** 48px
- **Border Radius:** 8px

#### Success Button
- **Background:** Emerald (#32D583)
- **Text Color:** Deep Charcoal (#0B0B0E)
- **Padding:** 16px horizontal, 12px vertical
- **Height:** 48px
- **Border Radius:** 8px

#### Danger Button
- **Background:** Coral (#E85A4F)
- **Text Color:** White (#FFFFFF)
- **Padding:** 16px horizontal, 12px vertical
- **Height:** 48px
- **Border Radius:** 8px

### Input Fields

#### States
1. **Default:**
   - Background: Interactive Dark (#1A1A1E)
   - Border: None
   - Text Color: Near White (#FAFAF9)
   - Placeholder: Muted Gray (#4A4A50)

2. **Focused:**
   - Background: Interactive Dark (#1A1A1E)
   - Border: 2px solid Indigo (#6366F1)
   - Text Color: Near White (#FAFAF9)

3. **Error:**
   - Background: Interactive Dark (#1A1A1E)
   - Border: 2px solid Coral (#E85A4F)
   - Text Color: Coral (#E85A4F)

#### Dimensions
- Height: 44–48px
- Padding: 12–14px horizontal
- Border Radius: 6–8px
- Font: DM Sans 13–14px

### Status Badges

| Status | Background | Text Color | Icon | Usage |
|--------|------------|-----------|------|-------|
| Complete | Emerald (#32D583) | Dark (#0B0B0E) | ✓ | Finished jobs |
| Processing | Coral (#E85A4F) | White (#FFFFFF) | ⟳ | Active jobs |
| Warning | Amber (#FFB547) | Dark (#0B0B0E) | ⚠ | Warnings |
| Pending | Gray (#6B6B70) | White (#FFFFFF) | ⏱ | Waiting state |

- **Height:** 24–28px
- **Padding:** 10–12px horizontal
- **Border Radius:** 12–14px (fully rounded)
- **Font:** DM Sans 11–12px 600

### Cards

#### Simple Card
- Background: Elevated Dark (#16161A)
- Padding: 20px
- Border Radius: 12px
- Shadow: Subtle shadow (4px blur, 8px offset)

#### Info Card (Colored)
- Background: Indigo (#6366F1)
- Padding: 16px
- Border Radius: 12px
- Text Color: White (#FFFFFF)

#### Error Card (Colored)
- Background: Coral (#E85A4F)
- Padding: 16px
- Border Radius: 12px
- Text Color: White (#FFFFFF)

### Icons

- **Font:** Lucide Icons
- **Sizes:** 16px, 18px, 20px, 24px
- **Stroke Weight:** 1.5px (default)
- **Color:** Inherits text color or specified fill

---

## Screen Designs

### 1. Home Page (1440x900)
**Purpose:** Entry point, document creation
**Key Elements:**
- Header with logo and account button
- Centered hero section with title and subtitle
- Form container with:
  - YouTube URL input
  - Presentation Mode toggle (enabled by default)
  - Create Document button
  - Import Document option
- Recent Documents section showing last jobs

**Layout:** Centered vertical layout with 80px horizontal padding

### 2. Job Detail – Workspace (1440x900)
**Purpose:** Document processing and editing interface
**Layout:** VS Code-inspired with 4 panes
- **Activity Bar** (60px width): Icon navigation with status indicators
- **Sidebar** (300px width): Transcript with time-indexed segments
- **Main Content:** Video player, tabbed content (Document/Snapshots/Slides)
- **Logs Panel** (150px height, collapsible): Processing logs and status

**Key Features:**
- Resizable panels using flexbox
- Tab interface for content switching
- Real-time logs with color-coded status

### 3. Settings Page (1440x900)
**Purpose:** User configuration and LLM provider selection
**Key Sections:**
- Header with back button
- LLM Provider selection (Ollama, OpenAI, Anthropic)
- Conditional fields based on provider:
  - Ollama: Base URL, Model Name
  - OpenAI: API Key
  - Anthropic: API Key
- Save Settings button

**Layout:** Vertical form centered with max-width 500px

### 4. Login Page (1440x900)
**Purpose:** User authentication
**Elements:**
- Centered card (420px width)
- Logo (32px Fraunces)
- Title: "Sign In"
- Form fields: Username/Email, Password
- Sign In button
- Footer links: Forgot password, Create account

**Layout:** Centered container with justify-center

### 5. Register Page (1440x900)
**Purpose:** Account creation
**Elements:**
- Centered card (420px width)
- Logo and title: "Create Account"
- Form fields: Username, Email, Password, Confirm Password
- Create Account button
- Footer: Link to Sign In

**Layout:** Centered container, same as Login

### 6. Forgot Password Page (1440x900)
**Purpose:** Password recovery initiation
**Elements:**
- Centered card (420px width)
- Title: "Forgot Password"
- Email input field
- Send Reset Link button
- Back to Sign In link

**Layout:** Minimal centered form

### 7. Reset Password Page (1440x900)
**Purpose:** Password reset completion
**Elements:**
- Centered card (420px width)
- Title: "Reset Password"
- New Password input
- Confirm Password input
- Update Password button
- Success message (green box with checkmark)

**Layout:** Centered form with success state

### 8. Dashboard Page (1440x900)
**Purpose:** Job management and overview
**Elements:**
- Header: "My Documents" with New Document button
- Stats section: Total, Completed, Processing counts
- Recent Documents table with:
  - Title column
  - Status badge
  - Created date
  - Action icons (open, download, delete)
- Scrollable table body

**Layout:** Full-width with 32px padding

---

## Mobile Responsive

### iPhone 14 Dimensions
- **Width:** 390px
- **Height:** 844px
- **Safe Area Padding:** 16px horizontal

### Mobile Home Page
- **Header:** 60px (compact)
- **Content:** Vertical stack with 16px padding
- **Form:** Full-width with 16px padding
- **Bottom Navigation:** 60px fixed tab bar with 3 items
  - Home (active)
  - Documents
  - Settings

### Mobile Navigation Bar
- **Height:** 60px
- **Layout:** Horizontal space-around
- **Items:** Icon (20px) + Label (10px font)
- **Active Color:** Emerald (#32D583)
- **Inactive Color:** Gray (#6B6B70)

### Mobile Loading State
- Full-screen centered layout
- Spinner (60px diameter)
- Title and description
- Progress bar (240px width)

### Responsive Breakpoints
```css
/* Tablet */
@media (max-width: 768px) {
  max-width: 90vw;
  padding: 16px;
  font-size: 14px;
}

/* Mobile */
@media (max-width: 480px) {
  max-width: 100vw;
  padding: 12px;
  font-size: 12px;
  gap: 12px;
}
```

---

## States & Variations

### Loading State
- **Icon:** Spinner (80px, stroke 4px, Indigo)
- **Title:** "Processing Your Document"
- **Description:** "Extracting transcript, snapshots, and generating summary..."
- **Progress Bar:** 42% example fill
- **Background:** Elevated Dark card

### Error State
- **Icon:** Circle X (80px, Coral)
- **Title:** "Processing Failed"
- **Description:** Contextual error message
- **Actions:** Retry button (Indigo), Dismiss button (Secondary)
- **Background:** Elevated Dark card

### Success State
- **Icon:** Circle Check (80px, Emerald)
- **Title:** "Document Ready!"
- **Description:** Success confirmation with stats
- **Actions:** View Document (Emerald), Download (Secondary)
- **Background:** Elevated Dark card

---

## Implementation Guide

### 1. Using This Design System

#### React/TypeScript Components

**Button Component:**
```typescript
interface ButtonProps {
  variant: 'primary' | 'secondary' | 'success' | 'danger';
  size: 'sm' | 'md' | 'lg';
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}

const Button: React.FC<ButtonProps> = ({ variant, size, ...props }) => {
  const styles = {
    primary: 'bg-indigo fill-white',
    secondary: 'bg-tertiary-bg border border-subtle',
    success: 'bg-emerald fill-charcoal',
    danger: 'bg-coral fill-white'
  };
  return <button className={`${styles[variant]} ...`} {...props} />;
};
```

#### CSS Custom Properties

```css
:root {
  /* Colors */
  --color-primary-bg: #0B0B0E;
  --color-secondary-bg: #16161A;
  --color-tertiary-bg: #1A1A1E;
  --color-text-primary: #FAFAF9;
  --color-text-secondary: #6B6B70;
  --color-border-subtle: #2A2A2E;
  --color-accent-green: #32D583;
  --color-accent-indigo: #6366F1;
  --color-accent-coral: #E85A4F;

  /* Spacing */
  --spacing-xs: 4px;
  --spacing-sm: 8px;
  --spacing-md: 16px;
  --spacing-lg: 24px;
  --spacing-xl: 40px;

  /* Typography */
  --font-serif: 'Fraunces', serif;
  --font-sans: 'DM Sans', sans-serif;
  --font-mono: 'Monaco', monospace;

  /* Border Radius */
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-pill: 24px;

  /* Shadows */
  --shadow-sm: 0 2px 12px rgba(0, 0, 0, 0.15);
  --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.25);
}
```

### 2. File Structure

```
youtube-model-feeder/
├── public/
│   └── design-system/
│       ├── new_youtube-model-feeder_ui.pen (Pencil file - Lunaris design)
│       ├── DESIGN_SPEC.md (This document)
│       └── assets/
│           ├── screenshots/ (Export PNG/SVG)
│           └── icons/ (Lucide SVG exports)
├── frontend/
│   ├── styles/
│   │   ├── colors.css (Color tokens)
│   │   ├── typography.css (Font scales)
│   │   └── spacing.css (Gap/padding)
│   └── components/
│       ├── Button/
│       ├── Input/
│       ├── Card/
│       └── Badge/
```

### 3. Export Instructions

#### From Pencil Design File

1. **Export Screens as PNG:**
   - Right-click screen → Export → PNG (2x for Retina)
   - Use for developer handoff and documentation

2. **Export Components as SVG:**
   - Select component → Export → SVG
   - Use for icon implementation

3. **Copy CSS Values:**
   - Each color/spacing value is documented above
   - Implement as CSS custom properties

#### Generate Figma/Design System
1. Import PNG screenshots into Figma
2. Create component library matching component specs
3. Document overrides and variants

### 4. Tailwind CSS Configuration

```javascript
module.exports = {
  theme: {
    colors: {
      charcoal: '#0B0B0E',
      'dark-elevated': '#16161A',
      'dark-interactive': '#1A1A1E',
      'text-primary': '#FAFAF9',
      'text-secondary': '#6B6B70',
      'border-subtle': '#2A2A2E',
      emerald: '#32D583',
      indigo: '#6366F1',
      coral: '#E85A4F',
      amber: '#FFB547'
    },
    spacing: {
      xs: '4px',
      sm: '8px',
      md: '16px',
      lg: '24px',
      xl: '40px'
    },
    borderRadius: {
      sm: '6px',
      md: '8px',
      lg: '12px',
      pill: '24px'
    },
    fontFamily: {
      serif: ['Fraunces', 'serif'],
      sans: ['DM Sans', 'sans-serif'],
      mono: ['Monaco', 'monospace']
    }
  }
};
```

---

## Saving & Sharing

### How to Save This Design

**Option 1: Pencil Native**
```bash
# Design file already created and committed:
# Location: new_youtube-model-feeder_ui.pen (project root)
# Status: Ready to use - Lunaris design system applied
```

**Option 2: Export for Figma**
```bash
# Export all screens as PNG:
# Pencil → each screen → Export → PNG
# Import into Figma → Create components
# Share Figma link with team
```

**Option 3: Export for Web**
```bash
# Create SVG exports:
# Pencil → Component Library screen → Export → SVG
# Store in: /public/design-system/components/
```

### Sharing with Team
1. **Designers:** Share Pencil file or Figma link
2. **Developers:** Share this spec (DESIGN_SPEC.md) + CSS tokens
3. **Stakeholders:** Share screenshot exports + interactive prototype link

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-02-28 | Initial design system, 8 screens, component library, mobile views, state variations |

---

## Contact & Support

For questions about this design system:
- **Design Files:** See `public/design-system/`
- **Questions:** Create an issue referencing DESIGN_SPEC.md
- **Updates:** Changes will be documented in Version History above

---

**Made with ❤️ using Pencil Design**
