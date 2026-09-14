# 五个 Benchmark Generate Query Pilot（每榜 5 条）

生成日期：2026-08-19

- 真实生成模型：`qwen3.8-max`，DashScope OpenAI-compatible API，`enable_thinking=false`。
- 输出范围：只生成最终态 Generate query；未生成测试步骤、Edit、Repair、Video 或 ground truth。
- Seed 方式：每条使用同一 benchmark/能力组内最多 4 条 seed；Web-Bench seed 已先把 20 步项目要求归并为最终态 query。
- 检查方式：结构校验、独立 Qwen reviewer、人工逐条复核。Qwen reviewer 初次接受 25 条，但人工发现 4 条问题并生成 replacement；本文只展示最终接受版本。
- Vision2Web 限制：公开的小型 L2 parquet 只含截断的 `prompt_preview` 和 prototype 文件名；本轮没有下载 2.63 GB `frontend.tar.gz`，因此这 5 条是 L2 文本风格 pilot，不是完整图像原型驱动的 native 样本。

## 汇总

| Benchmark | 最终接受 | 人工重做 |
|---|---:|---:|
| WebCompass | 5 | 1 |
| WebGen-Bench | 5 | 1 |
| Web-Bench | 5 | 2 |
| ArtifactsBench | 5 | 0 |
| Vision2Web | 5 | 0 |

## WebCompass

### 1. WC-1 commerce-social-transit

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a transaction or relationship journey with cross-page state
- Seed IDs：WebCompass:text-generation:463, WebCompass:text-generation:469, WebCompass:text-generation:474, WebCompass:text-generation:657
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a multi-page web application for 'GreenLease,' a platform connecting urban property owners with rooftop garden installers. The site must feature a shared shell with a sticky header containing navigation links (Home, Find Installer, My Projects, Resources) and a footer with legal links. Define four distinct routes: Homepage, Installer Directory, Project Dashboard, and Resource Library.
>
> **Homepage:** Hero section with value proposition and 'Start Your Project' CTA. Below, display three featured installer cards with ratings and specialties. Include a 'How It Works' step-by-step visual guide.
>
> **Installer Directory:** A searchable grid of installer profiles. Implement sidebar filters for service area, budget tier, and certification type. Each card shows a thumbnail, name, and 'View Profile' button. Clicking a profile navigates to a dedicated detail view within this route showing portfolio images and a 'Request Quote' form.
>
> **Project Dashboard:** A private user area displaying active project status. Show a vertical timeline tracker (Consultation -> Design -> Installation -> Maintenance). Include a message center list where users can click threads to view conversation history with their assigned installer. Persist the 'active project ID' state so returning users land directly on their current project phase.
>
> **Resource Library:** Categorized articles on permits, plant selection, and maintenance. Use a tag-based filtering system.
>
> **Cross-Page Flows:**
> 1.  **Quote Request:** User clicks 'Request Quote' on an Installer Directory card → Navigates to Project Dashboard → New project card appears in 'Consultation' phase with installer name pre-filled.
> 2.  **Resource Integration:** User reads a permit article in Resource Library → Clicks embedded 'Find Certified Installer' link → Navigates to Installer Directory with 'Certified' filter automatically applied.
>
> Use an eco-modern visual system with sage green accents, clean sans-serif typography, and consistent card styling. All navigation must resolve to valid internal routes without external dependencies.

页面/文件架构（审计字段，不进入训练 query）：

- /: Homepage with hero, featured installers, and process guide
- /installers: Searchable directory with filters and detail views
- /dashboard: Private project timeline tracker and message center
- /resources: Filtered knowledge base for permits and planting

### 2. WC-2 enterprise-systems

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one advanced enterprise productivity component or workflow
- Seed IDs：WebCompass:text-generation:785, WebCompass:text-generation:255, WebCompass:text-generation:664, WebCompass:text-generation:70
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=4/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> # Web Page Content
> ### 1. Layout & Information Architecture
> The application is a **Vendor Compliance & Risk Assessment Portal** designed for enterprise procurement teams. It features a focused, data-dense interface optimized for auditing external partners.
>
> **A. Global Shell**
> *   **Sidebar Navigation:** Dashboard, Vendor Registry, Active Assessments, Risk Matrix, Settings.
> *   **Top Bar:** Global Search (vendors/contracts), Notification Center, User Profile.
> *   **Breadcrumbs:** Contextual navigation for deep assessment flows.
>
> **B. Vendor Assessment Workspace (Core Feature)**
> This is the primary productivity surface where compliance officers evaluate vendor security posture.
> *   **Vendor Header:** Company Name, Logo, Overall Risk Score (Color-coded badge), Contract Expiry Date.
> *   **Split-Pane Interface:**
>     *   **Left Panel (Evidence Stream):** A scrollable list of required compliance artifacts (SOC2 reports, Insurance Certs, GDPR addendums). Each item shows status (Pending, Uploaded, Verified, Rejected).
>     *   **Right Panel (Interactive Checklist):** A hierarchical tree of control questions grouped by domain (e.g., Data Privacy, Physical Security).
> *   **Action Toolbar:** "Request Missing Info," "Generate Audit Report," "Approve Vendor."
>
> ---
> # Web Page Interaction
> ### 1. Primary Challenge: Synchronized Evidence-to-Control Linking
> The dominant implementation challenge is maintaining bidirectional state synchronization between the **Evidence Stream** and the **Checklist Tree**. When a user clicks an evidence document in the Left Panel, the Right Panel must automatically expand and highlight all related control questions that rely on that specific artifact. Conversely, clicking a control question should scroll the Left Panel to the relevant uploaded document. This requires a reactive mapping system where UI state updates instantly without page reloads or layout shifts.
>
> ### 2. Supporting Behaviors
> *   **Inline Status Toggling:** Users can change verification status (Verified/Rejected) directly within the checklist node via dropdowns. The change must optimistically update the Vendor Header's aggregate risk score immediately.
> *   **Contextual Commenting:** Clicking a "Flag" icon on any checklist item opens a non-blocking popover for adding auditor notes, which persists locally until saved.
>
> ### 3. Visual Direction
> Adopt a "Clinical Fintech" aesthetic: Slate-900 text on Off-White backgrounds, monospaced fonts for metadata/IDs, and semantic colors strictly reserved for risk states (Amber for warning, Emerald for compliant). Use subtle borders over heavy shadows to maintain information density.

页面/文件架构（审计字段，不进入训练 query）：

- layout.tsx: Global shell with sidebar and top bar
- dashboard/page.tsx: High-level risk matrix and overdue tasks summary
- assessment/[id]/page.tsx: Split-pane workspace with synchronized evidence and checklist panels
- components/EvidenceStream.tsx: Scrollable artifact list with filtering
- components/ControlChecklist.tsx: Hierarchical tree component with bidirectional linking logic

### 3. WC-3 media-learning

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：content discovery plus one hotspot-based learning interaction; exclude journals, collections, mini-games, comparison mode, and mastery analytics
- Seed IDs：WebCompass:text-generation:868, WebCompass:text-generation:124, WebCompass:text-generation:428, WebCompass:text-generation:698
- 人工结论：`accept_after_manual_revision`
- 重做原因：Original compact query accumulated unrelated journal, mini-game, comparison, and analytics systems.
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=4/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> # Web Page Content: Urban Foraging Field Guide
>
> ## Visual System & Layout
> *   **Aesthetic:** Organic minimalism using a palette of moss green, unbleached paper, and charcoal. Typography combines a readable serif for botanical descriptions with a clean sans-serif for UI elements.
> *   **Responsive Grid:** A masonry-style card layout for plant discovery that adapts from single-column on mobile to three-columns on desktop.
>
> ## Content Hierarchy
> 1.  **Discovery Hub (Home):**
>     *   **Seasonal Banner:** Dynamic header highlighting currently forageable species (e.g., "Late Summer Berries").
>     *   **Filter Bar:** Toggles for "Edible," "Medicinal," "Toxic Lookalikes," and "Habitat Type."
>     *   **Plant Cards:** Each card displays a high-contrast macro photo, common name, and a safety confidence badge.
> 2.  **Specimen Detail View:**
>     *   **Botanical Profile:** Scientific name, family, and detailed edibility notes.
>     *   **Hotspot Diagram:** A central anatomical illustration with interactive markers over leaves, stems, and fruit.
>     *   **Safety Warning Box:** High-visibility alert listing toxic lookalikes with comparison photos.
>
> # Web Page Interaction
>
> ## Core Workflow: Identification via Hotspots
> 1.  **Selection:** User clicks a Plant Card in the Discovery Hub to enter the Specimen Detail View.
> 2.  **Anatomy Exploration:** The central illustration features pulsing hotspot nodes. Hovering reveals a tooltip with micro-details (e.g., "Serrated leaf margin," "Hollow stem").
> 3.  **Verification Toggle:** Clicking a hotspot activates a "Verify" state. The node expands into a side-panel overlay showing a real-world reference photo alongside the diagram line art to confirm field identification.
> 4.  **Field Notes Action:** A persistent floating button allows users to tag the specimen as "Found Today," updating a local session log without navigating away from the learning interaction.
>
> ## Navigation States
> *   **Active Filters:** Persist across page reloads using URL parameters.
> *   **Back Navigation:** Returns user to the exact scroll position in the Discovery Hub.

页面/文件架构（审计字段，不进入训练 query）：

- /: Discovery hub with seasonal filters and masonry plant grid
- /specimen/:id: Detailed botanical profile with interactive anatomy hotspots and verification overlays

### 4. WC-4 games-simulation

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one stateful game or simulation mechanic
- Seed IDs：WebCompass:text-generation:291, WebCompass:text-generation:707, WebCompass:text-generation:555, WebCompass:text-generation:563
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> # Web Page Content
> **1. Layout Architecture**
> *   **Simulation Viewport:** A central, responsive HTML5 Canvas element (min-width 800px) serving as the primary rendering surface for the ecosystem. Background color should be a deep oceanic blue (#001e36).
> *   **Control Dashboard:** A fixed sidebar on the right (width 300px) containing simulation parameters and real-time statistics.
> *   **Overlay HUD:** Semi-transparent text in the top-left corner displaying current FPS and active entity count.
>
> **2. Visual Entities**
> *   **Prey (Boids):** Small teal triangles representing fish. They must exhibit flocking behavior with visible separation, alignment, and cohesion forces.
> *   **Predator:** A single larger red triangle that autonomously seeks the nearest cluster of prey.
> *   **Obstacles:** Static grey circles placed randomly or by user click that entities must avoid.
> *   **Trails:** Optional fading motion trails behind entities to visualize flow patterns.
>
> # Web Page Interaction
> **1. Primary Capability: Flocking Physics Engine**
> The core challenge is implementing Reynolds' Boids algorithm efficiently in vanilla JavaScript without external libraries. The system must calculate three steering behaviors per frame for up to 300 agents:
> *   **Separation:** Steer to avoid crowding local flockmates.
> *   **Alignment:** Steer towards the average heading of local flockmates.
> *   **Cohesion:** Steer to move toward the average position of local flockmates.
>
> **2. Interactive Controls**
> *   **Parameter Sliders:** Real-time adjustment of Perception Radius, Max Speed, and Separation Weight. Changes must apply immediately without resetting the simulation.
> *   **Mouse Interaction:** Clicking on the canvas spawns a static obstacle at that coordinate. Right-clicking removes the nearest obstacle.
> *   **Playback State:** Pause/Resume toggle button to freeze the physics loop while retaining the render state.
>
> **3. Visual Direction**
> Adopt a "Scientific Visualization" aesthetic using neon vector graphics against a dark background. Use additive blending for entities to create a bioluminescent effect when they overlap.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: Main simulation canvas and control dashboard

### 5. WC-5 data-workflows

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a data workflow spanning input, analysis, detail, and reporting
- Seed IDs：WebCompass:text-generation:351, WebCompass:text-generation:505, WebCompass:text-generation:478, WebCompass:text-generation:801
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a multi-page web application named 'FieldFix' for municipal infrastructure maintenance tracking. The app requires a shared shell with a top navigation bar (Dashboard, Inspections, Reports, Settings), user profile dropdown, and active route highlighting. Use a utilitarian visual system with high-contrast status colors and card-based layouts.
>
> **Required Routes:**
> 1.  **/dashboard**: Overview page displaying four KPI cards (Open Issues, Pending Review, Resolved This Week, Avg Resolution Time) and a recent activity feed. Includes a prominent 'New Inspection' button linking to /inspections/new.
> 2.  **/inspections**: Searchable, filterable data table listing infrastructure records. Columns: ID, Location, Type, Status Badge, Last Updated. Rows are clickable links to /inspections/:id. Includes filters for Status and Zone that update the table via client-side state.
> 3.  **/inspections/:id**: Detail view showing full record metadata, photo gallery placeholder, and chronological comment log. Features an 'Update Status' form that modifies local state and redirects back to /inspections upon success.
> 4.  **/reports**: Analytics page with a date-range picker controlling two charts: a stacked bar chart of issues by zone/type and a line chart of resolution trends. Includes a 'Export CSV' button simulating a file download.
> 5.  **/settings**: Configuration page for notification preferences and display density toggles.
>
> **Cross-Page Flows & State:**
> *   **Inspection Creation:** User clicks 'New Inspection' on Dashboard → fills form on /inspections/new → submits → new record appears at top of /inspections list with 'Pending' status.
> *   **Status Update:** User selects row in /inspections → views details on /inspections/:id → changes status to 'Resolved' → returns to /inspections where row badge updates instantly.
> *   **Persistence:** Maintain a global store for inspection records and filters. Navigating between /inspections and /reports must preserve filter selections and data mutations without resetting.

页面/文件架构（审计字段，不进入训练 query）：

- /dashboard: KPI overview and quick action entry point
- /inspections: Filterable master list of infrastructure records
- /inspections/:id: Detailed record view with status update capability
- /reports: Date-driven analytics and export functionality
- /settings: User preference configuration


## WebGen-Bench

### 1. WG-1 commerce-marketplace

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a complete catalog-to-explicit-detail-route-to-cart commerce journey; every referenced detail page must appear in the route architecture
- Seed IDs：WebGen-Bench:train:train_003382, WebGen-Bench:train:train_002981, WebGen-Bench:train:train_003363, WebGen-Bench:train:train_002991
- 人工结论：`accept_after_manual_revision`
- 重做原因：Original flow referenced a Product Detail page that was missing from its declared route architecture.
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a multi-page e-commerce website for 'Lumina Lighting', a boutique store selling artisanal lamps and fixtures. The site must include five distinct navigable routes: Home, Shop Catalog, Product Detail, Shopping Cart, and About Us. These must be separate pages with unique URLs, not modals or single-page sections. Implement a shared shell with a sticky header containing logo, navigation links with active states, and a cart icon showing item count; plus a footer with contact info. Use warm ivory (#FFFDD0) as the global background and burnt orange (#CC5500) for buttons, accents, and active nav indicators.
>
> Core user flows:
> 1. Catalog-to-Detail-to-Cart: User browses Shop Catalog, clicks a product card to navigate to its specific Product Detail route (e.g., /product/pendant-oak), views specs and images, then clicks 'Add to Cart'. This updates the persistent cart state and redirects to the Shopping Cart page where the item appears with quantity controls.
> 2. About-to-Shop: User reads brand story on About Us page, clicks embedded 'Explore Collection' link, and lands on Shop Catalog with all products visible.
>
> The Shop Catalog must support filtering by category (pendant, table, floor) and sorting by price. Each product in the catalog must link to a real, unique Product Detail route displaying name, price, description, materials, and add-to-cart button. The Shopping Cart must persist items across navigation, allow quantity adjustment, and display subtotal. All navigation links and contextual CTAs must resolve to valid internal routes—no dead ends or placeholder pages. Ensure responsive behavior: mobile hamburger menu, stacked layouts on small screens, and touch-friendly targets. Keep implementation self-contained with mock data; no external APIs or auth required.

页面/文件架构（审计字段，不进入训练 query）：

- /: Home page with hero banner and featured products
- /shop: Catalog page with filter/sort and product grid
- /product/:id: Individual product detail page with specs and add-to-cart
- /cart: Shopping cart page with item management and subtotal
- /about: Brand story page with contextual link to shop

### 2. WG-2 internal-enterprise

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：an enterprise workflow spanning dashboard, records, and settings
- Seed IDs：WebGen-Bench:train:train_001166, WebGen-Bench:train:train_002281, WebGen-Bench:train:train_001858, WebGen-Bench:train:train_002254
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Please implement an internal vendor compliance portal for tracking supplier certifications and audit status. The application must include four distinct navigable routes: Dashboard, Vendor Directory, Audit Workspace, and System Settings. These must be separate pages with unique URLs and content, not tabs or modals within a single view. A persistent sidebar navigation should highlight the active route and maintain the signed-in user session across all pages.
>
> The Dashboard displays summary widgets for expiring certificates and pending audits. Clicking a 'Review Pending' card navigates directly to the Audit Workspace pre-filtered to that specific vendor, where users can approve or reject documentation. This action immediately updates the vendor's compliance score visible in the Vendor Directory. The Vendor Directory lists all suppliers with sortable columns and status badges; clicking a vendor name routes to their dedicated Audit Workspace. System Settings allows administrators to manage certificate types and notification thresholds, with changes persisting globally without page reloads.
>
> Ensure every navigation link resolves to a functional internal route with substantive content. No dead links or placeholder pages are permitted. The interface must be fully responsive, collapsing the sidebar into a mobile menu on smaller screens while preserving all cross-page workflows. Visually, apply a background color of alice blue for the main canvas and use cadet blue for primary buttons, active navigation states, and table headers to establish a professional enterprise aesthetic. All interactive elements should provide clear hover and focus feedback consistent with this color scheme.

页面/文件架构（审计字段，不进入训练 query）：

- /dashboard: compliance overview and quick-action widgets
- /vendors: searchable supplier directory with status indicators
- /audit/:id: document review and approval workspace
- /settings: configuration for certificate types and alerts

### 3. WG-3 analytics-productivity

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one data-presentation or productivity capability
- Seed IDs：WebGen-Bench:train:train_000841, WebGen-Bench:train:train_005840, WebGen-Bench:train:train_000827, WebGen-Bench:train:train_005680
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Please implement a sprint velocity tracker designed for agile software teams to visualize development progress over time. The application must feature an interactive burn-down chart that dynamically renders remaining story points against ideal and actual progress lines across a two-week iteration cycle. Users should be able to hover over any data point on the chart to reveal a tooltip displaying the exact date, remaining points, and completed tasks for that specific day. The primary implementation challenge is ensuring the chart scales responsively within its container while maintaining precise alignment between the X-axis time labels and the plotted data points during window resizing events. As a supporting behavior, include a simple dropdown selector above the chart that allows users to switch between different mock sprint datasets without reloading the page, updating the visualization instantly. Another lightweight requirement is a summary statistics row beneath the chart showing total points committed, completed, and current variance percentage. The layout should consist of a centered main card containing the chart and controls, with ample whitespace to prevent visual clutter. Apply a soft lavender background to the overall page canvas and use deep slate blue for all chart lines, axis text, tooltips, and interactive UI components like the dropdown and stat cards. Ensure the color contrast meets accessibility standards for readability. The entire interface must remain fully functional and legible on mobile viewports by stacking the summary stats vertically and adjusting chart height proportionally.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: main responsive burn-down chart with dataset selector and summary statistics

### 4. WG-4 content-community

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：content presentation combined with one community interaction
- Seed IDs：WebGen-Bench:train:train_001573, WebGen-Bench:train:train_006032, WebGen-Bench:train:train_006125, WebGen-Bench:train:train_000582
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=4/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Please build a responsive web platform called 'CanvasCritique' designed for digital illustrators to share artwork and receive structured technical feedback. The primary purpose is to facilitate constructive peer reviews rather than simple social validation. The core workflow must combine an image gallery view with an inline annotation system. Specifically, users should be able to upload high-resolution illustrations that display in a masonry grid layout. When a user clicks an artwork, it opens a detailed lightbox view where they can toggle a 'Critique Mode'. In this mode, viewers can click specific coordinates on the image to leave pinned comments regarding anatomy, lighting, or composition, which appear as numbered markers linked to a sidebar discussion thread. This tightly couples content presentation with targeted community interaction. The interface must include a persistent navigation bar with links to Feed, My Portfolio, Notifications, and Guidelines. Ensure the layout adapts seamlessly from desktop to mobile, collapsing the sidebar into a bottom sheet on smaller screens while maintaining precise touch targets for placing annotation pins. Visually, adopt a professional studio aesthetic using charcoal (#36454F) as the global background color to reduce eye strain during long review sessions. Use amber (#FFBF00) for all interactive components, including buttons, active states, pin markers, and hover effects, ensuring high contrast against the dark theme. Typography should be clean sans-serif to prioritize readability of critique text over decorative elements.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: masonry feed and navigation
- artwork-detail.html: lightbox viewer with annotation overlay
- portfolio.html: user upload and management dashboard

### 5. WG-5 learning-games-media

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one learning, media, or browser-game interaction
- Seed IDs：WebGen-Bench:train:train_001515, WebGen-Bench:train:train_001585, WebGen-Bench:train:train_006579, WebGen-Bench:train:train_006255
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Please implement an interactive music theory learning application focused on real-time chord recognition practice. The primary capability is a browser-based piano interface where users press keys to identify chords displayed as visual prompts, receiving immediate feedback on accuracy and timing. The site must include exactly one dominant challenge: mapping simultaneous key presses to specific chord types (major, minor, seventh) with millisecond-precision input detection using the Web Audio API or keyboard event batching. Supporting behaviors are limited to a simple score counter that increments on correct answers and resets on page reload, plus a toggle button to switch between treble and bass clef notation displays. Do not implement user accounts, lesson progression systems, MIDI file imports, or audio recording features.
>
> The page structure should consist of a single-view layout containing a header with the app title and current score, a central canvas rendering dynamic sheet music notation that updates after each attempt, and a responsive virtual piano keyboard at the bottom that supports both mouse clicks and computer keyboard mapping (e.g., A-K for white keys). The piano must visually highlight pressed keys and provide color-coded feedback overlays (green for correct, red for incorrect) directly on the notation staff. Ensure the interface remains fully functional on tablet viewports by scaling the keyboard proportionally while maintaining touch target sizes above 44px.
>
> Apply a deep charcoal background (#2D2D2D) to reduce eye strain during extended practice sessions, use warm amber (#FFBF00) for active key highlights and correct-answer indicators, and style all UI controls and text in soft ivory (#FFFFF0) for high contrast readability. The overall aesthetic should feel like a modern digital instrument rather than a traditional educational quiz.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: Single-page chord identification practice interface with embedded piano and notation display


## Web-Bench

### 1. WB-1 routed-fullstack

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a final routed full-stack product
- Seed IDs：Web-Bench:expressjs:final-project, Web-Bench:nosql:final-project, Web-Bench:sequelize:final-project, Web-Bench:nextjs:final-project
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Build a complete Next.js application named 'GreenThumb Plant Exchange' from scratch using the App Router, node-sqlite3 for persistence, and jose for JWT authentication stored in a 'SESSION' cookie with secret 'PLANT-EXCHANGE-SECRET'. Do not use third-party UI libraries; implement all styling via custom CSS. Create a shared layout with a fixed header displaying '🌿 GreenThumb Plant Exchange' linking to home, and a UserMenu component showing login/register links for guests or a username dropdown with logout, profile, and my-swaps links for authenticated users. Include a fixed footer with copyright.
>
> Implement these distinct routes:
> 1. '/' (Home): Displays welcome message and featured plant cards linking to details.
> 2. '/browse': Lists all available plants with filter controls; each card links to detail page.
> 3. '/plants/:id': Shows plant details, owner info, and a 'Request Swap' button visible only to logged-in non-owners.
> 4. '/list-plant': Form for authenticated users to add new plants with name, species, description, and photo URL fields.
> 5. '/my-swaps': Dashboard showing incoming/outgoing swap requests with status badges and accept/decline actions.
> 6. '/profile/:username': Public profile displaying user bio and listed plants.
>
> Define cross-page flows: Clicking 'Request Swap' on /plants/:id creates a pending request and redirects to /my-swaps with success feedback. Accepting a swap on /my-swaps updates status and reflects changes on both users' dashboards. Persist swap request state across navigation. Implement API routes for auth, plants CRUD, and swap management. Enforce access control: users manage only their own plants and swaps. Use semantic class names like .plant-card, .swap-request-btn, .status-badge, and .filter-controls. Handle 404s with custom page. Ensure all navigation links resolve to valid internal routes.

页面/文件架构（审计字段，不进入训练 query）：

- /: Home page with featured plants and welcome message
- /browse: Searchable plant listing with filters
- /plants/:id: Individual plant detail with swap request action
- /list-plant: Authenticated form to add new plant listing
- /my-swaps: User dashboard for managing incoming/outgoing requests
- /profile/:username: Public user profile with plant inventory

### 2. WB-2 framework-routing

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a final framework-based product with real routes and shared state
- Seed IDs：Web-Bench:unocss:final-project, Web-Bench:angular:final-project, Web-Bench:tailwind:final-project, Web-Bench:svelte:final-project
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Build a self-contained React application using Vite and React Router v6 to create 'CivicPulse', a municipal issue reporting platform. The app must implement four distinct navigable routes within a shared shell containing a responsive navbar with active state styling and a consistent footer. Define these specific pages: '/' for the Dashboard, '/report' for submitting issues, '/tracker' for monitoring submissions, and '/resources' for community guidelines.
>
> The Dashboard route displays three summary statistic cards showing total reports, resolved count, and average resolution time derived from global state. It includes a prominent 'Report New Issue' button linking to /report. The Report page features a controlled form with fields for title, category dropdown (Pothole, Lighting, Sanitation), description textarea, and priority slider. Submitting validates inputs, adds the entry to a persistent context store with a generated ID and timestamp, triggers a success toast notification, and redirects to /tracker. The Tracker route renders a filterable list of all user-submitted issues sorted by date descending. Each list item is clickable and expands inline to show full details without navigation. Include a status toggle button on each expanded item that cycles between 'Open', 'In Progress', and 'Resolved', updating the shared state immediately. The Resources page contains static accordion sections explaining reporting protocols.
>
> Implement cross-page flows where navigating from Dashboard to Report preserves no temporary state, but returning to Tracker after submission shows the new entry at the top. Ensure the global issue store persists across all route transitions so status changes in Tracker reflect accurately if the user navigates away and returns. Use CSS Modules for scoped styling with a clean civic aesthetic using navy blue (#1e3a8a) and white tokens. All navigation links must resolve to valid internal routes; no external APIs or backend services are permitted. The final artifact must be a fully functional frontend demonstrating real routing, shared state management, and multi-step user journeys.

页面/文件架构（审计字段，不进入训练 query）：

- /: Dashboard displaying aggregate statistics and primary call-to-action
- /report: Form interface for creating new civic issue entries
- /tracker: Filterable list view for managing and updating issue statuses
- /resources: Static informational content with interactive accordions

### 3. WB-3 document-navigation

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：hierarchical document navigation plus one active table-of-contents behavior; exclude global search, theme switching, and unrelated URL-state systems
- Seed IDs：Web-Bench:sass:final-project, Web-Bench:esmodule:final-project, Web-Bench:bom:final-project, Web-Bench:less:final-project
- 人工结论：`accept_after_manual_revision`
- 重做原因：Original compact query accumulated navigation, TOC, search, theme, and URL-state systems.
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=4/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Build a self-contained technical documentation viewer named 'ApiLens' using HTML, CSS, and vanilla JavaScript ES modules. The application requires a main 'index.html' entry point loading 'styles.css' and 'app.js'. Create a modular content structure with three distinct documentation pages in a 'content' directory: 'authentication.html', 'endpoints.html', and 'errors.html'. Each content file must contain semantic section elements with unique IDs representing nested topics (e.g., <section id="oauth-flow"> containing <section id="token-refresh">).
>
> Implement a persistent left-sidebar navigation component in 'nav/Sidebar.js'. This module must parse the DOM of the currently loaded content page to dynamically generate a nested tree list reflecting the section hierarchy. The sidebar must support collapsible parent nodes for nested sections and automatically expand the path to the currently active section on load. Implement an IntersectionObserver-based scroll spy system that highlights the corresponding sidebar link as the user scrolls through the main content area. Clicking a sidebar item must smoothly scroll the main viewport to the target section and update the URL hash without reloading.
>
> Create a 'layout/MainLayout.js' module managing the two-column grid structure. The main content area must have independent scrolling from the sidebar. Include a sticky header within the content pane displaying the current document title derived from the h1 element. Ensure the sidebar remains fixed during content scrolling but adjusts height responsively. All styles should use CSS custom properties for spacing and colors to ensure consistent visual rhythm between the navigation tree and document prose. The final artifact must function entirely client-side, generating navigation structures purely from the static HTML content of each page without external build tools or frameworks.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: main application shell and layout container
- content/authentication.html: security and token management docs
- content/endpoints.html: API route reference with nested methods
- content/errors.html: error code catalog and troubleshooting
- nav/Sidebar.js: dynamic TOC generation and scroll spy logic
- layout/MainLayout.js: grid management and sticky header behavior
- styles.css: global typography and navigation styling

### 4. WB-4 visual-interactive

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one explicit Canvas, SVG, Three.js, or visual interaction capability
- Seed IDs：Web-Bench:svg-solar:final-project, Web-Bench:canvas:final-project, Web-Bench:pull-loading:final-project, Web-Bench:threejs:final-project
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Build a self-contained interactive SVG typography playground named 'kinetic-type' from scratch. The application must render a full-viewport SVG element with id 'canvas' and preserveAspectRatio 'xMidYMid meet'. Inside, define a <defs> block containing three distinct linearGradients (neon-blue, sunset-orange, toxic-green) and a Gaussian blur filter with id 'glow'. Render five <text> elements vertically stacked, each displaying the word 'MOTION' in uppercase sans-serif font. Implement a physics-based drag interaction where each text node acts as an independent physical body. On mousedown or touchstart on any text element, initiate a drag state that applies velocity based on pointer delta. Upon release, apply friction (0.92 decay) and elastic boundary collision so text bounces off viewport edges without escaping. The primary visual challenge is dynamic gradient mapping: calculate each text element's horizontal position relative to viewport width and interpolate between the three defined gradients in real-time during movement, updating the fill attribute every animation frame. Add a lightweight supporting behavior where hovering over stationary text triggers the 'glow' filter and scales the element to 1.1x over 200ms using CSS transitions on the SVG transform. Include a fixed-position HTML control panel overlaying the bottom-right corner with a reset button that animates all text back to their original centered stack positions using spring easing. Ensure the SVG uses pointer-events='all' for accurate hit testing and that gradient interpolation remains performant at 60fps during rapid dragging. All styles, scripts, and markup must be contained in a single index.html file without external dependencies.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: Single-file SVG canvas with embedded physics engine, gradient interpolation logic, and HTML control overlay

### 5. WB-5 core-dom-layout

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one native DOM drag-and-drop capability; CSS layout may support it but must not become a second primary challenge
- Seed IDs：Web-Bench:calculator-files:final-project, Web-Bench:grid:final-project, Web-Bench:dom1:final-project, Web-Bench:dom:final-project
- 人工结论：`accept_after_manual_revision`
- 重做原因：Original atomic query treated both CSS Grid and drag-and-drop as independent primary challenges.
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a single self-contained HTML file named index.html that implements a Kanban-style project board using native HTML5 Drag and Drop API. The page must use a dark theme with CSS variables for consistent styling and zero body margin. The layout consists of a fixed header containing the board title 'Sprint Planner' and a reset button, followed by a horizontal flex container holding exactly three column elements with classes 'column', labeled 'To Do', 'In Progress', and 'Done'. Each column must have a distinct header bar and a scrollable content area (class 'card-list') that accepts dropped items.
>
> Implement task cards as draggable div elements with class 'task-card'. Each card displays a title, priority badge, and unique data-id attribute. The primary challenge is implementing robust drag-and-drop reordering: users must be able to drag cards between columns and reorder them within the same column. During dragging, display a visual placeholder element indicating the exact drop position. Dropping a card must permanently update the DOM order and persist the new parent relationship. Prevent dropping cards outside valid column containers.
>
> Support two lightweight behaviors: first, include an 'Add Task' button in each column header that prompts for a title and appends a new draggable card to that specific list; second, implement double-click deletion where double-clicking any task card removes it from the DOM after confirmation. Visual feedback is required during all interactions: dragged cards should have reduced opacity, valid drop targets must highlight with a border accent color, and the placeholder must match card dimensions. Ensure the layout remains responsive so columns stack vertically on viewports narrower than 768px while maintaining full drag functionality. All logic must be vanilla JavaScript without external libraries, handling dragstart, dragover, dragenter, dragleave, and drop events to manage state and DOM manipulation precisely.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: Self-contained Kanban application with header, three-column layout, and embedded CSS/JS for drag-and-drop task management


## ArtifactsBench

### 1. AB-1 games

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one distinctive interactive game mechanic
- Seed IDs：ArtifactsBench:benchmark:1036, ArtifactsBench:benchmark:1642, ArtifactsBench:benchmark:8, ArtifactsBench:benchmark:1079
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=4/5，novelty=5/5

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Ensure the generated code is executable for demonstration. Create a browser-based puzzle game called "Chroma Shift" where players manipulate light beams using interactive prisms to illuminate specific target nodes on a grid.
>
> ### Core Mechanic
> The primary challenge is implementing real-time raycasting logic that calculates beam trajectories, reflections, and color blending instantly as users drag and rotate optical elements. Players must combine red, green, and blue light sources through additive color mixing to match the exact hue of locked gates or targets. For example, overlapping red and green beams must visually and logically produce yellow light to activate yellow receptors.
>
> ### Interaction & Feedback
> - **Direct Manipulation**: Allow smooth dragging and rotating of mirrors, splitters, and filters with mouse or touch input.
> - **Visual Validation**: Render laser paths with glowing neon effects against a dark background, providing immediate visual feedback when beams hit obstacles or successfully blend colors.
> - **Level Progression**: Include three pre-defined puzzle layouts of increasing complexity to demonstrate the mechanic's depth without requiring procedural generation.
>
> ### Visual Direction
> Adopt a sleek, futuristic aesthetic with a deep navy background and vibrant, emissive vector graphics. Use CSS shadows and canvas gradients to simulate light bloom. The UI should be minimal, focusing entirely on the puzzle grid and current objective status.
>
> ### Technical Constraints
> Implement this as a single self-contained HTML file using vanilla JavaScript and Canvas API. Do not use external physics engines or asset libraries. Prioritize performance so ray calculations remain smooth at 60fps during interaction. Add clear comments explaining the vector math used for reflection and intersection detection.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: main game canvas and UI overlay

### 2. AB-2 web-applications

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a coherent multi-page web application
- Seed IDs：ArtifactsBench:benchmark:875, ArtifactsBench:benchmark:427, ArtifactsBench:benchmark:1336, ArtifactsBench:benchmark:1082
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=4/5，novelty=5/5

Query：

> Build a multi-page web application called 'SynthWave Studio', a browser-based retro music production tool with a distinctive 1980s neon aesthetic. The app must contain four distinct navigable routes: '/studio' for the main sequencer interface, '/library' for browsing and managing sound presets, '/mixer' for real-time audio processing controls, and '/export' for rendering and downloading tracks. Implement a persistent global state for the current project that maintains track data, BPM, and volume levels across all page transitions without reloading.
>
> The /studio page should feature an interactive 16-step grid sequencer where users can toggle notes on/off with immediate visual feedback and play/pause functionality using local Web Audio API oscillators. The /library page must display categorized synth patches in a responsive card grid; clicking a patch card should navigate to /studio and automatically load that preset into the active channel. The /mixer page requires functional faders and knobs for EQ and reverb that update the shared audio context in real-time. Finally, the /export page should visualize the current arrangement as a waveform preview and provide a simulated render progress bar before enabling a download button.
>
> Ensure a consistent site shell with a glowing navigation bar highlighting the active route, CRT scanline overlays, and a cohesive purple/cyan color palette. All navigation links must resolve to valid internal routes with no dead ends. Cross-page flows are critical: selecting a sound in /library must persist and reflect immediately upon returning to /studio, and mixer adjustments made in /mixer must audibly affect playback when navigating back to /studio. Use vanilla JavaScript or React with local storage simulation for state persistence, avoiding any external API dependencies or authentication requirements.

页面/文件架构（审计字段，不进入训练 query）：

- /studio: main sequencer interface with step grid and transport controls
- /library: browsable preset cards with load-to-studio action
- /mixer: real-time EQ and effects processing controls
- /export: waveform visualization and simulated track rendering

### 3. AB-3 management-data

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：a focused management or data workflow
- Seed IDs：ArtifactsBench:benchmark:850, ArtifactsBench:benchmark:1401, ArtifactsBench:benchmark:498, ArtifactsBench:benchmark:939
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a sophisticated 'Greenhouse Climate Optimizer' single-page application for managing hydroponic grow zones. This tool should function as an interactive control center where facility managers can visualize environmental correlations and adjust automation parameters in real-time. The interface must feature a polished, dark-mode aesthetic with neon accent colors to distinguish between different sensor types (temperature, humidity, CO2, pH).
>
> ### Core Interactive Workflow
> 1. **Multi-Axis Correlation Chart**: Implement a responsive time-series visualization that overlays at least three distinct sensor metrics on shared axes. Users must be able to toggle individual data series via clickable legends and hover to see synchronized tooltips across all active metrics.
> 2. **Threshold Automation Builder**: Below the chart, provide a dynamic rule configuration panel. Allow users to define conditional logic (e.g., 'IF Humidity > 80% AND Temp < 18°C THEN Activate Dehumidifier'). Changes here should visually update a status indicator showing how many historical data points would have triggered this new rule.
> 3. **Zone State Simulator**: Include a control cluster that lets users manually override sensor values to test system responses without affecting real hardware. This simulation mode should pause live data ingestion and highlight overridden fields with a distinct warning state.
>
> ### Technical & Visual Requirements
> - Use mock JSON data representing 48 hours of high-frequency sensor readings.
> - Ensure the layout is responsive but optimized for desktop tablet views commonly used in agricultural tech.
> - All interactions must feel immediate; avoid page reloads when toggling charts or saving rules.
> - Code must be self-contained and executable for demonstration purposes, utilizing modern CSS for the glassmorphism effects on panels.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: Main dashboard shell with dark theme and navigation
- components/CorrelationChart.js: Multi-axis time-series visualization with sync tooltips
- components/AutomationBuilder.js: Conditional logic form with historical impact preview
- components/SimulatorPanel.js: Manual override controls with state management
- data/mockSensors.json: 48-hour high-frequency environmental dataset

### 4. AB-4 visual-simulation

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one SVG, Canvas, or simulation capability
- Seed IDs：ArtifactsBench:benchmark:150, ArtifactsBench:benchmark:128, ArtifactsBench:benchmark:21, ArtifactsBench:benchmark:102
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=4/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create an interactive SVG-based orbital mechanics simulator called 'Gravity Weaver' that visualizes gravitational slingshot trajectories in real-time. The application should feature a dark space-themed canvas with glowing neon orbital paths against a deep navy background. Users must be able to click and drag anywhere on the viewport to launch a probe, with the drag vector determining initial velocity and direction. The primary technical challenge is implementing accurate Newtonian gravity physics where the probe accelerates toward multiple static planetary bodies rendered as SVG circles with radial gradients. Each planet should have configurable mass values that visibly affect trajectory curvature. Include a trail rendering system using SVG polyline elements that updates every animation frame to show the probe's path history, fading opacity over time to indicate temporal progression. Add subtle particle effects at the probe position using small animated SVG circles that emit when passing within a threshold distance of any celestial body. The interface should include minimal HUD controls: a reset button styled as a circular icon, a speed multiplier slider, and a mass adjustment panel for each planet. Ensure smooth 60fps performance by optimizing DOM updates and using requestAnimationFrame for the physics loop. All graphics must be pure SVG without raster images or external libraries. The visual aesthetic should feel like a retro-futuristic mission control display with clean typography and precise geometric styling.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: main SVG canvas and physics engine
- styles.css: space theme and HUD styling
- physics.js: Newtonian gravity calculations and trajectory rendering

### 5. AB-5 multimedia-utility-other

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one multimedia, utility, or diagram interaction
- Seed IDs：ArtifactsBench:benchmark:1207, ArtifactsBench:benchmark:1422, ArtifactsBench:benchmark:1378, ArtifactsBench:benchmark:1488
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Build a browser-based 'Chromatic Waveform Sculptor' that transforms user-drawn gestures into synchronized audio-visual frequency landscapes. The primary challenge is implementing a real-time rendering pipeline where the vertical position of a continuous mouse or touch stroke directly modulates the amplitude of three layered sine wave oscillators, while the horizontal velocity controls the color hue shift speed across a dynamic canvas gradient. This requires tight coupling between the Web Audio API and HTML5 Canvas requestAnimationFrame loop to ensure zero-latency feedback without audio cracking or visual tearing.
>
> The interface should feature a minimalist dark-mode aesthetic with neon accent colors that respond to audio intensity. Include a central interactive viewport occupying 80% of the screen height where the drawing occurs, surrounded by a subtle glassmorphism control panel. Supporting behaviors include: (1) A 'Freeze Frame' toggle that locks the current visual state while allowing audio to continue evolving based on held input pressure, and (2) A smooth decay animation that fades both sound and visuals over two seconds when the user releases the pointer, preventing abrupt cutoffs.
>
> Avoid adding recording, file export, or preset management systems. Focus entirely on the expressive immediacy of the gesture-to-signal mapping. The code must be self-contained in a single HTML file with embedded CSS and vanilla JavaScript, ensuring it runs immediately in modern browsers without build steps. Prioritize performance optimization for mobile touch devices, handling multi-touch gracefully by averaging input coordinates rather than spawning multiple voices.

页面/文件架构（审计字段，不进入训练 query）：

- index.html: full-screen interactive canvas with overlay controls


## Vision2Web

### 1. V2W-1 content-community-publishing

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a content, community, or publishing journey
- Seed IDs：Vision2Web:Level2:community_hpe, Vision2Web:Level2:winecompanion, Vision2Web:Level2:forum_vectorworks, Vision2Web:Level2:yeacamp
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> I want to build a 'FieldNote Collective' website for independent nature writers and illustrators to publish serialized field journals. The site must contain five distinct navigable pages: Home, Journal Feed, Entry Detail, Author Profile, and Submit Entry. All pages share a consistent shell with an earthy color palette (sage green, cream, charcoal), serif typography for body text, and a sticky top navigation bar highlighting the active route.
>
> The Home page features a 'Featured Seasonal Collection' hero section and a grid of recent excerpts. Clicking any excerpt card navigates to the Entry Detail page, which renders the full article with inline image captions and a persistent 'Save to Reading List' button. This save state must persist across navigation using local storage, visually updating the button icon when toggled.
>
> The Journal Feed page displays a filterable list of entries by category (Botany, Ornithology, Mycology). Selecting an author's name from any entry card or feed item routes to the Author Profile page, showing their bio, location map placeholder, and a chronological archive of their work. From the Author Profile, users can click a 'Follow' button that updates a global follower count displayed in the site header.
>
> The Submit Entry page contains a structured form for title, category selection, markdown content, and image upload simulation. Upon successful submission, the user is redirected to the new entry's detail page, and the entry appears at the top of the Journal Feed. Ensure all navigation links resolve to valid internal routes with no dead ends. The application should function entirely client-side with mock data, requiring no backend authentication or external APIs.

页面/文件架构（审计字段，不进入训练 query）：

- /: Home with featured collections and recent excerpts grid
- /feed: Filterable journal listing by scientific category
- /entry/:id: Full article view with save-to-list functionality
- /author/:id: Creator profile with bio and publication archive
- /submit: Structured entry creation form with redirect on success

### 2. V2W-2 content-knowledge-multimedia

- 能力粒度：`atomic`
- 页面范围：`multi_page`
- 主要能力：one focused cross-page knowledge or multimedia capability
- Seed IDs：Vision2Web:Level2:cosmicshambles, Vision2Web:Level2:teacherserver, Vision2Web:Level2:theaccnz, Vision2Web:Level2:tcm
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> I want to build a multi-page website for 'FableForge', an interactive storytelling platform where users explore branching narrative archives. The site must contain five distinct navigable routes: Home, Archive, Story Reader, Author Profile, and About. These must be separate pages, not single-page tabs or modals. A shared shell includes a top navigation bar with active state highlighting, a consistent serif-and-slate color theme, and a footer with copyright and social links.
>
> The primary capability is cross-page narrative continuity. On the Archive page, users browse story cards filtered by genre. Clicking a card navigates to the Story Reader page, which loads that specific narrative chapter with text content and choice buttons. When a user selects a choice, the app persists their current story node ID and path history in local storage, then navigates to the next chapter route within the Story Reader. If the user leaves and returns via the Archive, a 'Continue Reading' button appears on previously started stories, resuming them at the exact saved node. This persistence must survive page reloads but reset if the user clicks 'Restart Story'.
>
> A secondary lightweight behavior is the Author Profile link embedded within each Story Reader chapter header; clicking it navigates to the dedicated Author Profile page displaying bio and other works by that writer. All navigation links and contextual references must resolve to valid internal routes. The Home page features a featured story spotlight and platform introduction. The About page contains static mission content. No external APIs, authentication, or backend services are allowed; all story data and state management must be handled client-side with mock JSON data embedded in the frontend.

页面/文件架构（审计字段，不进入训练 query）：

- /: Home - Featured story spotlight and platform introduction
- /archive: Archive - Browsable story cards with genre filtering
- /story/:id: Story Reader - Chapter display with choice-based navigation and persistent progress
- /author/:slug: Author Profile - Bio and bibliography for individual writers
- /about: About - Static mission statement and team information

### 3. V2W-3 transaction

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a complete transaction or service journey
- Seed IDs：Vision2Web:Level2:shopnshine, Vision2Web:Level2:oxford-flow, Vision2Web:Level2:maxviewrealty, Vision2Web:Level2:mojarto
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> I want to build a Sprout & Stem plant subscription service website. When someone opens the site, they land on a Homepage featuring an earthy green and cream color palette with a hero section promoting 'Curated Greenery Delivered Monthly.' The global navigation includes Home, Shop Plants, Subscription Plans, Plant Care Library, and Account, with active states clearly highlighted. The footer contains newsletter signup and social links consistent across all pages.
>
> The Shop Plants page displays individual plants in a responsive grid with filters for light requirements and pet safety. Clicking a plant card navigates to a Product Detail page showing high-resolution imagery, care specifications, and an 'Add to Cart' button. This action persists the item in a global cart state and updates the header cart counter without reloading.
>
> The Subscription Plans page presents three tiered options (Seedling, Grower, Botanist) with pricing toggles for monthly or quarterly billing. Selecting a plan navigates to the Checkout page, which displays the chosen subscription alongside any one-time add-ons from the cart. The Checkout page includes a simulated payment form and order summary; submitting this form redirects to an Order Confirmation page displaying a unique reference number and next delivery date.
>
> The Plant Care Library serves as an educational resource with searchable articles linked contextually from Product Detail pages. All navigation items and contextual links must resolve to distinct internal routes; no modals or single-page sections are permitted for primary content. The application should function entirely with local state management, requiring no external APIs or authentication backends.

页面/文件架构（审计字段，不进入训练 query）：

- /: Homepage with hero banner and category highlights
- /shop: Filterable plant catalog grid
- /product/:id: Individual plant details with add-to-cart functionality
- /plans: Subscription tier selection with billing toggle
- /checkout: Order review and simulated payment form
- /confirmation: Post-purchase success message and reference ID

### 4. V2W-4 saas

- 能力粒度：`compact`
- 页面范围：`multi_page`
- 主要能力：a SaaS master-detail or dashboard workflow
- Seed IDs：Vision2Web:Level2:casefox, Vision2Web:Level2:wildapricot, Vision2Web:Level2:smartrecruiters, Vision2Web:Level2:anomali
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> Create a multi-page SaaS prototype for 'StreamSync', a podcast production and guest management platform. The application must feature a consistent dark-themed shell with a persistent left sidebar navigation containing links to Dashboard, Episodes, Guests, and Settings, highlighting the active route. All navigation items must resolve to distinct, fully implemented pages rather than modals or tabs.
>
> The site requires four specific routes:
> 1. Dashboard: Displays high-level production metrics (episodes recorded this month, pending guests) and a 'Recent Activity' feed.
> 2. Episodes List: A filterable table showing episode titles, status badges (Draft, Scheduled, Published), and release dates.
> 3. Episode Detail: Shows comprehensive metadata, audio player placeholder, show notes editor, and linked guest profiles.
> 4. Guest Directory: A searchable grid of guest cards featuring avatars, expertise tags, and contact status.
>
> Implement two critical cross-page workflows with state persistence:
> - Workflow A: Clicking an episode row in the Episodes List navigates to the Episode Detail page, loading that specific episode's data. On the Detail page, clicking a linked guest name navigates to the Guest Directory filtered to show only that guest's profile.
> - Workflow B: From the Guest Directory, clicking 'Schedule Recording' on a guest card navigates to the Episodes List with a pre-applied filter showing only episodes associated with that guest.
>
> Maintain a mock 'current user' session across all pages so the sidebar reflects consistent authentication state. Ensure visual consistency using shared design tokens for typography, spacing, and status colors. Do not use external APIs; rely on internal mock data structures to demonstrate the master-detail relationships and navigation flow.

页面/文件架构（审计字段，不进入训练 query）：

- /dashboard: Production metrics overview and recent activity feed
- /episodes: Filterable master list of podcast episodes with status badges
- /episodes/:id: Detailed episode view with metadata, player, and guest links
- /guests: Searchable directory of guest profiles with scheduling actions

### 5. V2W-5 public-services

- 能力粒度：`atomic`
- 页面范围：`multi_page`
- 主要能力：one focused public-service application or information flow
- Seed IDs：Vision2Web:Level2:holyoke, Vision2Web:Level2:myimmitracker, Vision2Web:Level2:elections_bc
- 人工结论：`accept`
- Qwen reviewer：`accept`；benchmark=5/5，granularity=5/5，topology=5/5，boundary=5/5，feasibility=5/5，novelty=5/5

Query：

> I want to build a CivicFix municipal reporting portal that allows residents to submit and track non-emergency infrastructure issues. The site must contain four distinct navigable pages: Home, Report Issue, My Reports, and FAQ. These must be separate routes with unique content, not tabs or modals within a single view. A shared site shell includes a top navigation bar highlighting the active page, a consistent teal and white color scheme using CSS variables, and a footer with department contact info.
>
> The primary implementation challenge is a persistent multi-step reporting flow on the Report Issue page. Users select a category (e.g., Pothole, Broken Light), fill out location and description fields, and submit. Upon submission, the system generates a unique tracking ID stored in localStorage and redirects the user to the My Reports page. This destination page must read from localStorage to display the newly created ticket alongside any previously saved reports in a status table showing ID, Category, Date, and Status.
>
> A secondary cross-page flow requires the Home page to feature a prominent 'Report New Issue' hero button that navigates directly to the pre-scrolled form section of the Report Issue route. Additionally, the FAQ page must include contextual links referencing specific report categories that navigate back to the Report Issue page with that category pre-selected via URL query parameters.
>
> Visual consistency is mandatory across all routes. Navigation links must resolve to real internal paths; no dead links are permitted. Do not implement backend authentication, admin dashboards, or map APIs. The entire application must function as a self-contained frontend prototype relying solely on browser storage for state persistence between the reporting form and the tracking dashboard.

页面/文件架构（审计字段，不进入训练 query）：

- /: Landing page with hero CTA and service overview
- /report: Multi-step issue submission form with validation
- /my-reports: Persistent tracking dashboard reading from localStorage
- /faq: Informational resource with deep links to report categories
