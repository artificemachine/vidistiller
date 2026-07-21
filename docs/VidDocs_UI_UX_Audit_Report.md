# Vidistiller — UI/UX Design Audit Report

**Date:** February 26, 2026
**Prepared for:** Maxime Roy
**Based on:** Current design trends from Mobbin, Dribbble, Aura, and 2026 SaaS best practices

---

## 1. Executive Summary

This audit evaluates the Vidistiller web application across three screens: the Home/Landing page, the Jobs Dashboard, and the Job Detail Workspace. The review is informed by current design patterns from Mobbin, Dribbble, Aura, and 2026 SaaS conversion best practices, as well as techniques documented in the Gemini 3 design workflow note from the project vault.

Vidistiller has a solid foundation: a clear value proposition, a well-structured VS Code-like workspace metaphor, and a functional dark mode. However, several issues impact both usability and conversion, ranging from a critical authentication bug on the Dashboard to visual polish gaps that reduce perceived quality.

**Key findings:** 2 critical bugs, 3 high-priority UX issues, and 7 design polish recommendations.

---

## 2. Issues Summary

| Severity | Area | Description |
|----------|------|-------------|
| **CRITICAL** | Dashboard | "Failed to load jobs" error and "No jobs yet" empty state display simultaneously. Mutually exclusive states are not handled correctly. |
| **CRITICAL** | Dashboard Auth | Dashboard accessible to unauthenticated users despite route requiring auth. Edge middleware may not be catching this route. |
| **HIGH** | Landing CTA | "Login to Convert" button mixes authentication with the primary action. Splits user intent and adds friction for logged-in users. |
| **HIGH** | Landing Page | No social proof anywhere (usage numbers, testimonials, trusted-by logos). Major conversion gap per 2026 SaaS best practices. |
| **HIGH** | Transcript | Green `[HH:MM:SS]` timestamps visually dominate the reading experience. Text content should be the primary focus. |
| **MEDIUM** | Landing Page | "Import Saved Job" section exposes technical .json import on a marketing-oriented page. Should be tucked behind secondary UI. |
| **MEDIUM** | Cards / Elevation | All cards are flat dark rectangles with no border differentiation or depth. No glassmorphism, gradients, or shadows. |
| **MEDIUM** | Processing Logs | Logs remain expanded after job completion. Should auto-collapse when status is "completed." |
| **MEDIUM** | Sidebar Icons | Activity Bar icons lack labels or tooltips. Poor discoverability for non-obvious icons. |
| **MEDIUM** | Snapshot Button | Full-width blue Snapshot bar competes visually with the video player. Should be smaller or an overlay. |
| **MEDIUM** | Typography | Insufficient type hierarchy. Most text appears at similar weight/size, making it hard to scan. |
| **LOW** | Dead Code | Legacy components (TranscriptDisplay, DocumentDisplay, VideoSubmission) are exported but unused. |

---

## 3. Page-by-Page Analysis

### 3.1 Home / Landing Page

#### What Works

- The headline "Turn YouTube videos into docs" is clear and benefit-focused — exactly what 2026 landing page best practices recommend: instant clarity on what the tool does and who it's for.
- Single-column centered layout keeps focus on the primary action.
- Dark mode execution is clean with appropriate contrast ratios.

#### Recommended Changes

**Split the CTA:** The "Login to Convert" button performs double duty as both an auth gate and an action trigger. Current SaaS conversion patterns emphasize having one primary CTA that communicates the action, not a prerequisite. Show "Convert" as the CTA for logged-in users, and redirect to login only when triggered. Semrush and other top-converting SaaS pages put the action front and center without friction language.

**Add Social Proof:** Every top-performing landing page in 2026 includes social proof above or just below the fold. Add usage numbers, a testimonial quote, or "trusted-by" logos. Even a simple counter like "500+ videos converted" adds credibility and reduces hesitation.

**Relocate Import Feature:** The "Import Saved Job" section with its `.json` drop zone feels like a developer feature on a marketing page. On Mobbin, the best SaaS hero sections keep the above-the-fold area focused on one action. Move the import feature behind a Dashboard menu item, an "Advanced" toggle, or a secondary link.

**Add Visual Depth:** Looking at Aura templates and Dribbble trends, even minimal dark-mode SaaS sites use subtle background gradients, mesh/grain textures, or glassmorphism card effects to add depth. Consider adding a subtle border gradient or soft drop shadow to the conversion card, as described in the Gemini 3 design workflow note.

---

### 3.2 Jobs Dashboard

#### Bugs

**Mutual exclusion failure:** The "Failed to load jobs" error and "No jobs yet. Create one" message display simultaneously. These states must be mutually exclusive. If the API call fails, show the error with a retry button. If it succeeds and returns empty, show the empty state. The fix is straightforward in the `useState`/`useEffect` fetch logic: render error state OR empty state OR list, never both.

**Auth bypass:** The Dashboard appears accessible to logged-out users (nav shows "Login" instead of the user menu). The route map specifies `/dashboard` requires auth, and the Edge middleware should redirect to `/login`. Either the middleware is not catching this route, or there is a client-side race condition where the page renders before `AuthProvider` finishes `initialize()`. Verify the middleware matcher pattern includes `/dashboard`.

#### Design Gaps

**Empty state is dead space:** Current SaaS dashboard best practices emphasize that even empty states should be useful. Show an illustration, a quick-start guide, or a sample job to demonstrate value. Mobbin's "Sections" filter feature shows how the best products structure their empty states with actionable content.

**No visual hierarchy:** The "Jobs Dashboard" heading, error banner, and empty state card are all roughly the same visual weight. Use typography scale and spacing to create clear information layers.

---

### 3.3 Job Detail Workspace

This is the core product experience and has the most room for improvement.

#### Transcript Panel

**Timestamp styling:** The green `[00:00:00]` timestamps dominate the reading experience. On every design platform researched, the trend is to soften secondary information. Timestamps should be smaller, lighter (`text-gray-500` base), and use `hover:text-blue-400` with a subtle underline on hover. This keeps them discoverable as clickable seek targets without dominating the transcript text. The spec confirms these are clickable elements that seek the player, so they need to remain clearly interactive — but subdued at rest.

**Toolbar visibility:** The Summary / Export / Save buttons are small and easy to miss. Current UI patterns from Mobbin show that primary actions in editor-style apps use more prominent, clearly labeled buttons with icons + text rather than icons alone.

#### Player Panel

**Snapshot button:** The full-width "Snapshot" button in solid blue competes visually with the video player. Based on Dribbble patterns for media editing UIs, a better approach would be an overlay button on the video player itself (camera icon on hover), or a smaller button in a toolbar below the player.

#### Processing Logs

**Auto-collapse after completion:** The logs panel takes significant space for information that is irrelevant once processing is complete. The Activity Bar already supports toggling this panel. Add logic to auto-collapse when `job.status === 'completed'`, showing a green "Processing complete" summary with an expandable accordion for full logs.

#### Activity Bar

**Discoverability:** The four sidebar icons lack labels or tooltips. Discoverability research on Mobbin consistently shows that icon-only navigation works only when icons are universally recognized (home, search, settings). Custom or ambiguous icons need at least a tooltip on hover. Add `title` attributes or a tooltip component to each Activity Bar button.

---

## 4. Design Reference: Better Stack Uptime (Mobbin)

The following patterns are drawn from Better Stack's Uptime dashboard (curated by Mobbin) and are directly applicable to Vidistiller.

### 4.1 Onboarding Checklist for Empty States

Better Stack shows a "Get the most out of Better Stack" card on the dashboard with a progress indicator ("5 out of 6 steps left") and expandable task cards. Each step has a clear action label and a brief description. Completed steps show a green checkmark; pending steps show an open circle.

**Application to Vidistiller Dashboard:** Replace the current "No jobs yet. Create one" dead space with a getting-started checklist:

1. Convert your first video
2. Capture snapshots while watching
3. Generate an AI summary
4. Export your documentation to Obsidian
5. Import a saved job

This gives new users a clear path to value and makes the empty Dashboard feel purposeful rather than broken. The progress indicator ("2 out of 5 steps") provides motivation to explore features.

### 4.2 Incident Detail Card Layout

Better Stack's incident detail page uses clearly separated cards with distinct sections: "Cause" (monospace code block), "Created by / Started at / Length" (three equal-width cards in a row), and "Escalation" (full-width card below). Each card has a small gray label above a large bold value, creating strong visual hierarchy.

**Application to Vidistiller Job Detail:** The job metadata (Job ID, YouTube URL, language, status, created date) is currently compressed into the transcript panel header. Break this out into a structured card layout:

- A "Status / Created / Duration" row of small cards at the top of the sidebar, using the same label-above-value pattern
- "Source URL" as a clickable link card
- This separates metadata from content and makes the job state scannable at a glance

### 4.3 Sidebar Navigation with Labels and Count Badges

Better Stack's sidebar uses icon + text labels for every navigation item, with count badges (e.g., "Incidents 2") for items that need attention. The active item has a highlighted background.

**Application to Vidistiller Activity Bar:** The current icon-only Activity Bar should adopt this pattern. At minimum, add tooltip labels on hover. Ideally, when the sidebar is expanded, show icon + text labels. Add a count badge to the snapshots icon showing how many snapshots have been captured.

### 4.4 Status Indicators and Success Banners

Better Stack uses a green success banner ("Incident was successfully reported and the team will be notified") for confirmations, and a red dot + "Ongoing" label for active status. The "Acknowledge" button is prominently placed with a green highlight.

**Application to Vidistiller:** The processing status could adopt this pattern more clearly — show a green banner when processing completes ("Your documentation is ready"), and use the dot + label pattern for the NavStatusBadge in the navbar to make job status more scannable.

---

## 5. Design System Recommendations

### 5.1 Dark Mode Refinement

The current dark background is functional but flat. The 2026 trend confirmed across Dribbble and dark mode design guides is to use dark grey (`#121212` to `#1E1E1E`) rather than near-black, and create depth through subtle elevation layers. Cards should be slightly lighter than the background, with soft borders or glassmorphism effects. The current UI has everything at the same elevation.

### 5.2 Typography Hierarchy

Most text appears to be a similar weight and size. Modern SaaS dashboards use at least 3–4 distinct type scales to create scannable hierarchy. Headings, body text, timestamps, and metadata should each have a clearly different size, weight, and color. The existing Tailwind token system supports this — it just needs more differentiation in practice.

### 5.3 Micro-interactions

There are no visible hover states, transitions, or loading animations. Even small touches — a button color shift on hover, a subtle fade when panels resize, a skeleton loader during processing — would make the app feel significantly more polished. The Gemini 3 design note emphasizes that border beam animations and scroll-triggered effects are now achievable with minimal code.

### 5.4 Border Gradients and Shadows

As demonstrated in the Aura design tool and referenced in the Gemini 3 note, border gradients and drop shadows are key differentiators for modern dark-mode UIs. Adding a subtle border gradient to the main conversion card and workspace panels would immediately elevate the perceived quality. Tailwind supports this via custom utilities.

---

## 6. Prioritized Action Plan

| # | Priority | Action | Effort | Impact |
|---|----------|--------|--------|--------|
| 1 | **Critical** | Fix Dashboard mutual-exclusion bug (error vs empty state) | Low | High |
| 2 | **Critical** | Fix Dashboard auth middleware to redirect unauthenticated users | Low | High |
| 3 | **High** | Split "Login to Convert" CTA into proper "Convert" button with auth redirect | Low | High |
| 4 | **High** | Add social proof section to landing page | Medium | High |
| 5 | **High** | Soften transcript timestamp styling (smaller, lighter, hover state) | Low | Medium |
| 6 | **Medium** | Auto-collapse processing logs when job completes | Low | Medium |
| 7 | **Medium** | Add tooltips to Activity Bar icons | Low | Medium |
| 8 | **Medium** | Add border gradients / elevation to cards across all pages | Medium | Medium |
| 9 | **Medium** | Relocate Import Job section behind secondary UI | Low | Low |
| 10 | **Medium** | Resize Snapshot button to overlay or compact toolbar | Low | Low |
| 11 | **Low** | Delete legacy unused components (TranscriptDisplay, DocumentDisplay, VideoSubmission) | Low | Low |
| 12 | **Low** | Add micro-interactions (hover states, transitions, skeleton loaders) | Medium | Medium |

---

## 7. Key Techniques from Gemini 3 Design Workflow

The following techniques are extracted from the Gemini 3 design note in the project vault and are directly applicable to Vidistiller redesign work.

### Inspiration Feeding

Rather than using generic prompts, feed AI design tools (Gemini 3, Cursor, v0) with screenshots of reference designs from Mobbin or Dribbble. A picture provides far more context than text descriptions. Start with the hero section — once the hero establishes the visual language, all subsequent sections will be consistent in style, animation, and branding.

### Style Combining

Take an existing template and combine it with a different design reference. For example: "Keep the cards from Template A but change the rest to match the style of Screenshot B." This mix-and-match approach produces original designs that are more creative than either source alone. This is particularly relevant for Vidistiller — the workspace layout could adopt card patterns from Better Stack while keeping the VS Code panel metaphor.

### Icon and Logo Strategy

Always specify icon libraries upfront in prompts: Iconify Solar Duotone for UI icons, SVG Logos for brand/company logos. This prevents AI from generating placeholder icons that need manual replacement later. Vidistiller should adopt a consistent icon library across the Activity Bar, toolbar buttons, and status indicators.

### Animation Patterns

Border beam animations, scroll-triggered reveals (animate on scroll), and keyframe animations add significant perceived quality. These can be prompted directly: "animate border beam using yellow" or "add animate on scroll and animate keyframe." For Vidistiller, applying border beam to the active panel or scroll-triggered fade-in to transcript sections would add polish with minimal code.

### Background Depth with Unicorn Studio

For hero sections and landing pages, Unicorn Studio backgrounds (beams, glyphs, light trails) add visual depth without competing with foreground content. The key rule: the background should never be in the way of the elements in front. Choose backgrounds with empty space that don't overlap headings or CTAs. Adjust blend mode (screen), saturation, brightness, and blur to ensure the foreground remains dominant.

---

## 8. Research Sources

### Design Inspiration Platforms

- **[Mobbin](https://mobbin.com)** — World's largest UI/UX reference library with 300,000+ screens. The 2025 Mobbin Sites launch added section-level and style-level filtering for web design patterns.
  - [Mobbin Sites (Web Design)](https://mobbin.com/browse/web/apps)
  - [Mobbin on Product Hunt](https://www.producthunt.com/products/mobbin)
- **[Dribbble](https://dribbble.com)** — Design showcase platform for browsing web design inspiration and wireframe references.
  - [Dribbble Web Design Tag](https://dribbble.com/tags/web-design)
  - [Dribbble Dark Mode Designs](https://dribbble.com/tags/dark-mode)
- **[Aura](https://www.aura.build)** — AI-powered HTML design tool with templates, border gradients, drop shadows, and Unicorn Studio background integration.
- **[Affinity](https://affinity.serif.com/en-us/)** — Free professional design tool with modern interaction patterns.
- **[Panda](https://usepanda.com)** — Design aggregator pulling from Dribbble, Product Hunt, and other sources.
- **[La Ninja (Lapa Ninja)](https://www.lapa.ninja)** — Curated gallery of real production landing pages with full screenshots.
- **[UI Verse](https://uiverse.io)** — Free community library of buttons, cards, loaders, and toggles for micro-interaction patterns.
- **[21st.dev](https://21st.dev)** — Polished dark-mode React component library with production-ready code.
- **[Unicorn Studio](https://www.unicorn.studio)** — Interactive background and animation tool (beams, glyphs, light trails) for embedding in web layouts.
- **[Better Stack](https://betterstack.com)** — Uptime monitoring platform with exemplary dashboard design: onboarding checklists, incident detail card layouts, sidebar navigation with count badges, and status banners. Curated on Mobbin as a design reference.

### Industry Resources

- **[Hero Section Examples and Best Practices](https://blog.logrocket.com/ux-design/hero-section-examples-best-practices/)** — LogRocket Blog
- **[Landing Page Best Practices That Convert in 2026](https://lovable.dev/guides/landing-page-best-practices-convert)** — Lovable
- **[40 Best Landing Page Examples of 2026](https://unbounce.com/landing-page-examples/best-landing-page-examples/)** — Unbounce
- **[Top Landing Page Design Trends for B2B SaaS in 2026](https://www.saashero.net/content/top-landing-page-design-trends/)** — SaaS Hero
- **[Marketing SaaS Landing Pages — 12 Designs That Convert](https://designrevision.com/blog/marketing-saas-landing-pages)** — DesignRevision
- **[Website Hero Section Best Practices + Examples](https://prismic.io/blog/website-hero-section)** — Prismic
- **[9 Modern Landing Page Examples to Inspire You in 2026](https://blog.helpfulhero.com/9-modern-landing-page-examples-to-inspire-you-in-2026)** — Helpful Hero
- **[Landing Page Best Practices 2026 — A Structure That Converts](https://toimi.pro/blog/landing-page-design-structure-conversion/)** — Toimi

### Project References

- **Gemini 3 Changes Everything for Web Design** — [Obsidian vault note](obsidian://open?vault=&file=notes/web_design/gemini_3_changes_everything_for_web_design) — Techniques for inspiration feeding, style combining, and animation with AI design tools. [Source video](https://youtu.be/b-kTkak2FKs).
- **Vidistiller UI/UX Design Document** (project spec) — Full component inventory, state management, theming, and route map.
