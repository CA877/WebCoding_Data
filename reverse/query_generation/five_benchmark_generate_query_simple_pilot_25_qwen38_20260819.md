# 五榜 Generate Query 简化 Pilot（每榜 5 条）

生成日期：2026-08-19

- 真实生成模型：`qwen3.8-max`。
- 生成方式：同榜、同能力组的真实 query seeds + benchmark 独立风格/能力约束。
- 检查方式：长度、JSON、页面数和跨页流程的确定性结构检查，随后人工阅读；未调用独立 LLM reviewer，也未执行 reviewer 驱动的定向重写。
- 输出范围：仅最终态 Generate query；没有测试步骤、checklist、Edit、Repair、Video 或 ground truth。
- 数量：25 条；其中 multi-page 12 条。成功记录 token 合计 64,714；失败尝试的 token 未进入该统计。
- Vision2Web 限制：本轮使用公开 L2 prompt preview、prototype 文件名及论文 taxonomy；没有下载完整 prototype 图像包，因此属于 L2 文本 query pilot。

## 人工阅读记录

- 五个 benchmark 的 25 个预定能力槽位均已有 query；所有 multi-page 样本都声明了 3--6 个审计页面和两条跨页流程。
- WebCompass 的长度范围最终按本轮真实 seeds 调整为 650--1300 词；原 700--900 词阈值窄于官方 seed 的 672--1171 词实际范围。
- `WB-1 routed-fullstack` 的正文实际提到了多于六个 URL，虽然审计字段只列出六个主要页面；它符合 Web-Bench 长最终态任务的特点，但比本轮“3--6 个主要页面”目标更密集。
- `WB-2 framework-routing` 同时称 Dashboard 为 `/dashboard` 和 `/`，实现时需要将 `/` 明确为重定向或别名。这是当前 raw pilot 中最明显的路由歧义。
- `WC-1 commerce-social-transit` 加入了登录、API 和 server confirmation 等实现语义，较原定的纯用户可见行为边界更重；是否保留取决于后续扩量时是否希望覆盖带账户状态的交易站点。
- 上述候选没有因这些人工意见再次交给 Qwen 改写；本文按用户要求展示生成阶段的原始成品和问题边界。

## WebCompass

### 1. WC-1 commerce-social-transit

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a transaction or relationship journey with cross-page state
- Query 词数：1159
- Seed IDs：WebCompass:text-generation:463, WebCompass:text-generation:469, WebCompass:text-generation:474, WebCompass:text-generation:657

Query：

> # Web page content
> This section defines the functional architecture, content hierarchy, and navigational structure for the Artisan Roast Subscription Platform. The application facilitates a transactional journey where users curate personalized coffee subscriptions and manage ongoing deliveries.
>
> ### 1. Global Site Shell
> *   **Persistent Header:**
>     *   **Brand Identity:** Text-based logotype aligned left.
>     *   **Primary Navigation:** Horizontal menu items: "Shop Blends," "Subscription Builder," "Brew Guides," "Our Story."
>     *   **Utility Actions:** Search icon, Account Profile link, and Cart Summary (displaying item count badge).
>     *   **Active State Indicator:** Visual underline or highlight beneath the current page's navigation link.
> *   **Site Footer:**
>     *   **Columnar Layout:** Links organized into "Shop," "Support," "Company," and "Legal."
>     *   **Newsletter Signup:** Email input field with a subscribe button.
>     *   **Social Proof:** Row of payment method icons and social media links.
>
> ### 2. Homepage (Discovery & Entry)
> *   **Hero Section:** Full-width lifestyle imagery featuring coffee preparation. Overlay contains a headline ("Craft Your Perfect Morning") and two primary CTAs: "Start Subscription" and "Browse Single Origins."
> *   **Featured Rotations:** A horizontal carousel displaying three seasonal blends with tasting notes, price, and quick-add buttons.
> *   **Value Proposition Grid:** Three-column layout highlighting "Ethically Sourced," "Roasted to Order," and "Flexible Delivery" with accompanying iconography.
> *   **Educational Teaser:** Link to the Brew Guides section with a preview thumbnail of the latest tutorial.
>
> ### 3. Subscription Builder (Configuration Engine)
> *   **Step Indicator:** Horizontal progress bar showing four stages: Profile, Flavor, Frequency, Review.
> *   **Flavor Profiler Module:**
>     *   **Interactive Sliders:** Range inputs for Acidity, Body, Sweetness, and Roast Level.
>     *   **Tasting Note Tags:** Clickable chips (e.g., "Chocolate," "Citrus," "Nutty") that toggle selection state.
> *   **Cadence Selector:** Radio card group for delivery frequency (Weekly, Bi-Weekly, Monthly). Each card displays a dynamic price-per-cup calculation based on selection.
> *   **Size & Grind Options:** Dropdown selectors for bag weight (12oz, 2lb, 5lb) and grind type (Whole Bean, Espresso, Drip, French Press).
> *   **Live Preview Panel:** Sticky sidebar updating in real-time to show selected blend match, total cost, and next estimated delivery date as user adjusts inputs.
>
> ### 4. Product Detail Page (PDP)
> *   **Media Gallery:** Main product image with thumbnail strip for origin map, bean close-up, and packaging shot.
> *   **Product Metadata:** Title, price, origin region, altitude, processing method, and roast date.
> *   **Sensory Radar Chart:** Visual polygon chart representing the five key taste attributes.
> *   **Add-to-Cart Module:** Quantity selector, grind option, and primary CTA. Includes "Save to Subscription" secondary action.
> *   **Related Content:** Tabbed interface for "Tasting Notes," "Brewing Recommendations," and "Farmer Story."
>
> ### 5. Customer Dashboard (Management Hub)
> *   **Welcome Banner:** Personalized greeting and loyalty tier status.
> *   **Active Subscriptions Card:** Displays current blend, next shipment date, and quick actions: "Pause," "Skip Next," "Change Blend."
> *   **Order History Table:** Chronological list of past orders with status badges (Processing, Shipped, Delivered) and reorder buttons.
> *   **Saved Preferences:** Quick access to previously liked blends and flavor profile settings.
>
> ### 6. Cross-Page User Flows
> *   **Flow A: Subscription Creation Journey.** User navigates from Homepage Hero CTA to Subscription Builder. After configuring flavor profile and cadence, user proceeds through Review step and confirms subscription. System redirects to Customer Dashboard with new active subscription visible at top of list and success toast notification displayed.
> *   **Flow B: Discovery to Recurring Conversion.** User browses Product Detail Page via Shop Blends navigation. User clicks "Save to Subscription" button instead of one-time add-to-cart. System prompts login or account creation if guest. Upon authentication, user is redirected to Subscription Builder with product pre-loaded as base blend, preserving original PDP context within configuration flow.
>
> ---
>
> # web page interaction
> This section specifies observable behaviors, feedback mechanisms, and state transitions across the platform.
>
> ### 1. Navigation & Routing Feedback
> *   **Route Transitions:** Page changes trigger a subtle fade-in effect for main content area to prevent jarring white flashes.
> *   **Active Link States:** Navigation items display animated underline expansion on hover; solid underline persists for current route.
> *   **Mobile Menu:** Hamburger icon transforms to X on open; slide-out drawer overlays content with backdrop blur.
>
> ### 2. Subscription Builder Interactions
> *   **Slider Feedback:** Dragging flavor sliders updates numeric value label instantly; releasing triggers debounce recalculation of blend match in Live Preview Panel.
> *   **Tag Selection:** Clicking tasting note tags toggles filled/outline state with scale micro-animation. Selected tags persist across step navigation.
> *   **Cadence Pricing Update:** Selecting frequency radio card immediately recalculates and animates price-per-cup number transition in preview panel.
> *   **Form Validation:** Invalid fields display red border and helper text below input on blur; submit button disables until all required fields valid.
> *   **Step Progression:** Completing step enables next button with color shift; back button always enabled except on first step.
>
> ### 3. Commerce Interactions
> *   **Add-to-Cart Feedback:** Button displays loading spinner during API call; on success, transforms to checkmark state briefly before reverting. Cart badge count increments with bounce animation.
> *   **Quick View Modal:** Hovering product card on grid reveals overlay with essential info; clicking opens modal without leaving current page.
> *   **Image Gallery:** Thumbnail click swaps main image with crossfade; swipe gestures supported on touch devices.
>
> ### 4. Dashboard Management
> *   **Action Confirmation:** Clicking "Pause" or "Skip" triggers confirmation dialog explaining impact on billing cycle; cancel returns to previous state.
> *   **Status Updates:** Modifying subscription displays optimistic UI update immediately; server confirmation reinforces with green success banner.
> *   **Table Sorting:** Clicking column headers reorders rows with smooth row repositioning animation.
>
> ---
>
> # web page visual
> This section establishes the design system, aesthetic guidelines, and component styling for consistent visual language.
>
> ### 1. Design Philosophy
> *   **Aesthetic Direction:** "Warm Minimalism." Clean layouts with generous whitespace balanced by organic textures and earthy warmth. Avoids sterile e-commerce coldness while maintaining modern usability.
> *   **Visual Hierarchy:** Typography-driven with imagery supporting rather than dominating. Content breathes through intentional spacing.
>
> ### 2. Color System
> *   **Background Palette:**
>     *   Primary: Warm Cream (`#FAF7F2`) for main surfaces to reduce blue-light harshness.
>     *   Secondary: Soft Clay (`#E8DDD3`) for card backgrounds and section differentiation.
> *   **Typography Colors:**
>     *   Headings: Deep Espresso (`#2C1810`) for strong contrast and thematic resonance.
>     *   Body: Charcoal Brown (`#4A3728`) for comfortable extended reading.
>     *   Muted: Taupe (`#8B7355`) for captions and secondary metadata.
> *   **Accent & Action Colors:**
>     *   Primary CTA: Terracotta (`#C65D3B`) for buttons and active states.
>     *   Success: Sage Green (`#7A9E7E`) for confirmations and positive indicators.
>     *   Error: Muted Rust (`#B54835`) for validation messages.
>
> ### 3. Typography Scale
> *   **Headings:** Elegant serif typeface conveying craftsmanship and heritage. Weights: Regular for H3-H4, Bold for H1-H2.
> *   **Body Copy:** Neutral sans-serif optimized for readability at small sizes. Line-height set generously for scanning comfort.
> *   **Data & Labels:** Monospaced font for prices, measurements, and technical specs to reinforce precision and artisanal quality.
>
> ### 4. Component Styling
> *   **Buttons:** Rounded corners (4px radius). Primary buttons use solid Terracotta fill with cream text; secondary buttons use outline style with Terracotta border. Hover states darken fill by 8%.
> *   **Cards:** No drop shadows; instead use 1px border in Soft Clay color. Hover lifts card 2px with subtle shadow emergence.
> *   **Inputs:** Bottom-border-only style for cleaner aesthetic; focus state expands border width and shifts color to Terracotta.
> *   **Icons:** Line-art style with 1.5px stroke weight. Consistent optical sizing across navigation and UI elements.
>
> ### 5. Imagery Treatment
> *   **Photography Style:** Natural lighting, shallow depth of field, warm color grading matching site palette. Avoid over-saturated commercial stock aesthetic.
> *   **Aspect Ratios:** Product images maintain consistent 4:5 ratio; lifestyle hero images use 16:9 cinematic crop.
> *   **Loading States:** Skeleton placeholders use Soft Clay color with gentle pulse animation rather than generic gray.

页面/文件架构（审计字段，不进入 query）：

- Homepage: Discovery entry point with hero content and featured products
- Subscription Builder: Multi-step configuration engine for personalized plans
- Product Detail Page: Individual blend information and purchase options
- Customer Dashboard: Account management and subscription control hub

跨页流程（审计字段）：

- User navigates from Homepage Hero CTA to Subscription Builder, completes configuration through Review step, and is redirected to Customer Dashboard with new active subscription visible and success notification displayed
- User browses Product Detail Page via Shop navigation, clicks Save to Subscription instead of one-time purchase, authenticates if guest, and is redirected to Subscription Builder with product pre-loaded as base blend preserving original context

### 2. WC-2 enterprise-systems

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one advanced enterprise productivity component or workflow
- Query 词数：871
- Seed IDs：WebCompass:text-generation:785, WebCompass:text-generation:255, WebCompass:text-generation:664, WebCompass:text-generation:70

Query：

> # Web page content
> ### 1. Page Structure & Information Architecture
> The application is a specialized **Clinical Trial Protocol Builder** designed for research coordinators to construct complex medical study workflows without coding. It operates as a single-page workspace with three distinct zones: **Protocol Canvas**, **Criteria Library**, and **Validation Console**.
>
> **A. Global Navigation Shell**
> *   **Left Sidebar (Collapsible):**
>     *   Project Selector dropdown showing active trial name and ID.
>     *   Navigation items: Study Overview, Visit Schedule, Eligibility Criteria, Data Collection Forms, Regulatory Documents.
>     *   Version History icon linking to previous protocol snapshots.
> *   **Top Utility Bar:**
>     *   Breadcrumb trail indicating current section depth.
>     *   "Save Draft" status indicator with timestamp.
>     *   Collaboration toggle showing active reviewers.
>     *   Export button for PDF/Word generation.
>
> **B. Protocol Canvas (Primary Workspace)**
> This is the core authoring environment where users define the temporal structure of the clinical trial.
> *   **Timeline Visualization:** A horizontal Gantt-style track representing study visits (e.g., Screening, Baseline, Week 4, Follow-up). Each node represents a discrete clinical encounter.
> *   **Visit Configuration Panel:** When a timeline node is selected, a slide-over panel appears containing:
>     *   Visit Name and Window Tolerance inputs (e.g., "+/- 3 days").
>     *   Procedure Checklist: Searchable multi-select list for labs, vitals, ECGs, and drug administration.
>     *   Notes Field: Rich text area for site-specific instructions.
> *   **Drag-and-Drop Reordering:** Users can rearrange visit nodes chronologically by dragging handles, which automatically recalculates relative day targets.
>
> **C. Eligibility Criteria Builder**
> A structured logic editor for defining inclusion/exclusion rules.
> *   **Logic Blocks:** Stacked cards representing individual criteria (e.g., "Age >= 18", "HbA1c < 7.0%").
> *   **Operator Selectors:** Dropdowns for AND/OR/NOT grouping between blocks.
> *   **Variable Picker:** Autocomplete input referencing the data dictionary defined in the canvas.
>
> **D. Validation Console**
> A persistent bottom drawer that surfaces real-time compliance checks.
> *   Error List: Specific messages like "Visit 3 window overlaps with Visit 4" or "Missing required lab at Baseline."
> *   Warning List: Soft alerts for best practices (e.g., "No safety follow-up defined after last dose").
> *   Compliance Score: Percentage indicator of protocol completeness against ICH-GCP guidelines.
>
> # web page interaction
> The primary interaction challenge is managing the dependency between the visual timeline and the underlying logical constraints without causing disorientation. When a user drags a visit node on the Protocol Canvas to reorder the schedule, the system must immediately recalculate all dependent date windows and eligibility lookback periods. During this recalculation, the dragged node should remain visually anchored to the cursor while non-selected nodes shift fluidly to accommodate the new position. If the drop location creates a logical conflict (e.g., placing a post-treatment visit before the dosing visit), the node must snap back to its original position with a subtle shake animation, and the Validation Console must instantly expand to highlight the specific constraint violation in red.
>
> Secondary interactions focus on reducing cognitive load during criteria definition. In the Eligibility Criteria Builder, typing into the Variable Picker input triggers a filtered dropdown that categorizes matches by type (Demographics, Labs, Vitals). Selecting a variable automatically populates adjacent operator and value fields with context-aware defaults (e.g., selecting "Age" defaults operator to ">=" and value to "18"). Hovering over any criterion block displays a tooltip preview showing how many hypothetical patients would pass/fail based on current parameters, providing immediate feedback on rule strictness without leaving the editor.
>
> Global state management ensures data integrity across views. Clicking "Save Draft" triggers an optimistic UI update where the status indicator switches to a spinning sync icon, then resolves to a green checkmark with the new timestamp. If the save fails due to network issues, the indicator turns amber and retries silently; only after three failures does it display a non-blocking toast notification offering manual retry. This prevents interruption of the deep-focus authoring flow common in protocol design.
>
> # web page visual
> The visual system prioritizes clinical precision and reduced eye strain during long authoring sessions. The color palette uses a "Medical Slate" foundation: background surfaces are soft cool grey (#F8FAFC) rather than pure white to reduce glare. Primary actions and active states use a trustworthy Teal (#0D9488), avoiding aggressive blues or alarming reds except for critical validation errors. Timeline nodes use semantic coloring: Blue for screening, Green for treatment, Amber for follow-up, and Grey for optional visits. Text hierarchy relies on weight and size rather than color alone; headings are Dark Slate (#1E293B), body text is Medium Grey (#475569), and metadata labels are Light Grey (#94A3B8).
>
> Typography employs a technical sans-serif family optimized for tabular data density. Headings use tight tracking for scanability, while numeric inputs and timeline scales use tabular figures to ensure vertical alignment in columns. Line height is generous (1.6) in rich text areas but compact (1.2) in configuration panels to maximize visible information density without clutter. Borders are hairline (1px) and subtle (#E2E8F0), using elevation shadows only for floating panels and tooltips to establish z-index hierarchy clearly.
>
> Component states communicate system status unambiguously. Selected timeline nodes have a solid Teal border and light fill; hovered nodes show a dashed outline. Disabled elements appear at 40% opacity with no pointer events. Loading states avoid generic spinners; instead, skeleton screens mirror the exact layout of the Protocol Canvas or Criteria Cards to maintain spatial orientation during data fetches. Empty states feature instructional illustrations in muted teal line art, guiding users toward the first actionable step rather than displaying barren whitespace.

页面/文件架构（审计字段，不进入 query）：

- /workspace/canvas: Visual timeline editor for defining study visits and procedures
- /workspace/criteria: Structured logic builder for inclusion/exclusion rules
- /workspace/validation: Real-time compliance checking and error resolution console

### 3. WC-3 media-learning

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：content discovery plus one hotspot-based learning interaction; exclude journals, collections, mini-games, comparison mode, and mastery analytics
- Query 词数：1055
- Seed IDs：WebCompass:text-generation:868, WebCompass:text-generation:124, WebCompass:text-generation:428, WebCompass:text-generation:698

Query：

> # Web page content
>
> ### 1. Global Navigation & Layout Structure
> *   **Header Bar:**
>     *   **Brand Identity:** Logo positioned top-left representing "CircuitFlow," an interactive electronics learning platform.
>     *   **Primary Navigation:** Horizontal links for "Component Library," "Learning Paths," "Community Projects," and "My Workbench."
>     *   **Utility Area:** Global search bar with autocomplete for component names (e.g., "555 Timer," "NPN Transistor") and a user profile avatar dropdown.
> *   **Footer:**
>     *   **Resource Links:** Datasheets repository, Safety guidelines, Soldering tutorials.
>     *   **Legal & Social:** Privacy policy, Terms of use, GitHub link, Discord community invite.
>     *   **Newsletter:** Input field for "Weekly Circuit Challenges" subscription.
>
> ### 2. Component Discovery Hub (Catalog Page)
> *   **Filter Sidebar (Left Column):**
>     *   **Category Tree:** Expandable accordion menus for Passive Components, Semiconductors, Integrated Circuits, Electromechanical, and Power Sources.
>     *   **Parameter Filters:** Dynamic checkboxes and range sliders based on selected category (e.g., Voltage Rating, Tolerance, Package Type).
>     *   **Availability Toggle:** Switch to show only components currently in the virtual lab inventory.
> *   **Component Grid (Main Content):**
>     *   **Card Layout:** Responsive grid displaying individual electronic components.
>     *   **Card Anatomy:** High-resolution product photo, Component Name, Part Number, Key Spec Badge (e.g., "5V Logic"), and a "Quick Add" icon button.
>     *   **Hover Preview:** Hovering over a card reveals a mini-spec tooltip showing pinout diagram and primary function without navigating away.
> *   **Featured Collection Banner:** Rotating carousel highlighting thematic sets like "Arduino Starter Kit Essentials" or "Audio Amplifier Basics."
>
> ### 3. Interactive Hotspot Learning Module
> This is the core educational interface accessed when selecting a specific component from the discovery hub.
> *   **Central Visualization Stage:**
>     *   **High-Fidelity Render:** A photorealistic, rotatable 3D model or detailed vector illustration of the component centered on screen.
>     *   **Hotspot Markers:** Subtle pulsing indicators overlaid on critical physical features (e.g., pins, leads, casing markings, polarity stripes).
> *   **Contextual Information Panel (Right Side):**
>     *   **Dynamic Content Area:** Updates instantly when a hotspot is activated.
>     *   **Content Hierarchy:** Feature Name (H2), Technical Explanation (Body text), Common Pitfall Warning (Alert box), and Real-world Application Example.
>     *   **Related Media:** Small thumbnail gallery linking to schematic symbols and footprint diagrams relevant to the selected hotspot.
> *   **Knowledge Check Overlay:**
>     *   **Micro-Quiz Trigger:** After exploring three distinct hotspots, a non-intrusive prompt appears asking a verification question (e.g., "Which pin is the collector?").
>     *   **Feedback Mechanism:** Immediate visual confirmation (green check/red X) with a brief explanatory correction if answered incorrectly.
>
> ---
>
> # Web page interaction
>
> ### 1. Discovery Phase Interactions
> *   **Smart Filtering:** Selecting a parent category in the sidebar immediately updates the grid without page reload. Parameter filters are context-aware; selecting "Capacitors" removes "Transistor Gain" filters and adds "Capacitance Range."
> *   **Search Behavior:** Typing in the global search triggers a debounced dropdown showing matching components, categories, and learning modules. Clicking a result navigates directly to that entity.
> *   **Grid Sorting:** Users can toggle between "Relevance," "Newest," and "Complexity Level." The transition between sort orders uses a staggered fade animation to maintain spatial awareness.
> *   **Quick Add Feedback:** Clicking the "Quick Add" icon on a card triggers a toast notification at the bottom-right confirming addition to the current workbench session, with an undo option available for five seconds.
>
> ### 2. Hotspot Exploration Sequence
> *   **Hotspot Activation:** Clicking a pulsing marker pauses its animation and expands it into a focused state. The camera/view subtly zooms toward the selected feature to provide visual emphasis.
> *   **Panel Transition:** Content in the right-side panel slides in from the right with a smooth easing curve. Previous content fades out simultaneously to prevent layout shift jarring.
> *   **Cross-Referencing:** Clicking a schematic symbol thumbnail in the info panel opens a lightbox overlay comparing the physical component view with its abstract circuit representation side-by-side.
> *   **Navigation Flow:** "Next Feature" and "Previous Feature" buttons allow sequential exploration for users who prefer guided learning over free exploration. Keyboard arrow keys also trigger this navigation.
>
> ### 3. Knowledge Verification Loop
> *   **Quiz Presentation:** The micro-quiz appears as a modal overlay with a semi-transparent backdrop blur, keeping the component visible but de-emphasized.
> *   **Answer Selection:** Options are presented as large, tappable cards rather than small radio buttons to accommodate touch interfaces. Hover states indicate selectability.
> *   **Feedback Timing:** Correct answers trigger a success animation and auto-dismiss the quiz after two seconds, returning focus to the next unexplored hotspot. Incorrect answers shake gently, display the correction text, and require manual dismissal to ensure the user reads the explanation.
> *   **Progress Tracking:** A subtle progress ring around the component visualization fills as hotspots are explored, providing ambient feedback on learning completion status without numerical scores.
>
> ---
>
> # Web page visual
>
> ### 1. Color System & Theming
> *   **Base Palette:** Dark mode default to reduce eye strain during extended study sessions and mimic professional EDA software environments.
>     *   **Background:** Deep Charcoal (`#1E1E1E`) for main canvas, Slightly Lighter Gray (`#252526`) for panels and cards.
>     *   **Surface Elevation:** Modals and overlays use `#2D2D30` to distinguish from base layers.
> *   **Semantic Accents:**
>     *   **Interactive/Active:** Electric Blue (`#007ACC`) for primary actions, active hotspots, and links.
>     *   **Success/Correct:** Muted Emerald (`#4EC9B0`) for positive feedback and completed states.
>     *   **Warning/Pitfall:** Amber Orange (`#CE9178`) for cautionary notes and common mistake alerts.
>     *   **Error/Incorrect:** Soft Red (`#F44747`) used sparingly only for quiz failures.
> *   **Text Hierarchy:**
>     *   **Primary:** Off-White (`#D4D4D4`) for body text and headings.
>     *   **Secondary:** Medium Gray (`#858585`) for metadata, labels, and disabled states.
>
> ### 2. Typography & Readability
> *   **Headings:** Geometric Sans-Serif (e.g., *Inter* or *DM Sans*) for clean, technical aesthetic. Bold weight for H1/H2 to establish clear section boundaries.
> *   **Body Text:** Humanist Sans-Serif optimized for screen reading. Line height set to 1.6 for comfortable scanning of technical explanations.
> *   **Technical Data:** Monospace font (e.g., *JetBrains Mono* or *Fira Code*) exclusively for part numbers, pin designations, code snippets, and electrical values to distinguish data from prose.
> *   **Scale:** Modular type scale with consistent ratios. H1 significantly larger than body to anchor the hotspot detail view.
>
> ### 3. Component Styling & States
> *   **Cards:** Subtle 1px border using surface color (`#3E3E42`). No heavy drop shadows; elevation conveyed through background color contrast and minimal inner glow on hover.
> *   **Hotspots:** Concentric circle design. Outer ring pulses with low opacity; inner dot is solid accent color. Active state removes pulse and increases size slightly.
> *   **Buttons:** Rectangular with 4px border radius. Primary buttons filled with accent color; secondary buttons outlined. All buttons have distinct focus rings for keyboard accessibility.
> *   **Imagery:** Component renders must have transparent backgrounds to blend seamlessly with dark theme. Specular highlights preserved to convey material properties (metal vs. plastic).
> *   **Motion Principles:** All transitions use ease-out curves for natural deceleration. Duration kept under 300ms for UI responses to maintain snappy feel. Content reveals prioritize opacity fades over complex transforms to avoid distracting from technical content.

页面/文件架构（审计字段，不进入 query）：

- /discovery: Component catalog with filtering and search
- /component/[id]: Interactive hotspot learning module with contextual info panel

### 4. WC-4 games-simulation

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one stateful game or simulation mechanic
- Query 词数：863
- Seed IDs：WebCompass:text-generation:291, WebCompass:text-generation:707, WebCompass:text-generation:555, WebCompass:text-generation:563

Query：

> # Web page content
> This section outlines the structural hierarchy and informational components necessary for the fluid dynamics simulation interface.
>
> **1. Page Layout Architecture:**
> *   **Global Header:**
>     *   **Application Title:** A distinct heading displaying "Viscous Flow Lab."
>     *   **Simulation Metrics Bar:** A horizontal strip presenting real-time telemetry:
>         *   **Particle Count:** Live integer counter representing active fluid nodes.
>         *   **Average Velocity:** Floating-point readout updating per frame.
>         *   **Viscosity Index:** Current resistance coefficient value.
> *   **Primary Simulation Viewport:**
>     *   **Fluid Canvas:** A large, central rectangular rendering area where the particle system operates. This is the focal point of the application.
>     *   **State Overlays:**
>         *   **Initialization Screen:** A centered modal appearing on load, containing the title, a "Initialize Fluid" button, and a brief explanation of mouse interaction (e.g., "Click and Drag to Stir").
>         *   **System Paused Indicator:** A subtle semi-transparent overlay triggered when the user halts simulation, displaying "Paused" and a "Resume" action.
> *   **Control Dashboard (Right Panel):**
>     *   **Parameter Sliders:** Vertical or horizontal range inputs for adjusting physics constants:
>         *   **Viscosity Control:** Adjusts fluid thickness from water-like to honey-like.
>         *   **Gravity Vector:** Modifies downward force magnitude.
>         *   **Dissipation Rate:** Controls how quickly velocity fades over time.
>     *   **Emitter Tools:** Buttons to spawn different fluid types (e.g., "Dye Injector," "Force Emitter").
>     *   **Reset Action:** A prominent button to clear the canvas and reset all parameters to default.
>
> **2. Simulation Entities:**
> *   **The Fluid Medium:**
>     *   **Particles:** Thousands of discrete points that collectively behave as a continuous medium. They must exhibit cohesion, separation, and alignment behaviors.
>     *   **Velocity Field:** An invisible grid storing directional momentum that influences particle movement.
> *   **Interaction Proxies:**
>     *   **Mouse Cursor:** Acts as a physical collider or force emitter within the simulation space.
>     *   **Boundary Walls:** Invisible barriers at the canvas edges that reflect particles and prevent escape.
>
> **3. Informational Feedback:**
> *   **Hover Tooltips:** Explanatory text appearing when hovering over slider labels to define physical units.
> *   **Active State Indicators:** Visual highlighting on the currently selected emitter tool.
> *   **Performance Warning:** A subtle text alert if particle count exceeds optimal rendering thresholds.
>
> # web page interaction
> This section defines the observable user behaviors and system responses governing the simulation experience.
>
> **1. Primary Interaction Loop:**
> *   **Stirring Mechanic:** When the user clicks and drags within the Fluid Canvas, the cursor acts as a dynamic force emitter. Particles within a specific radius should accelerate in the direction of the mouse movement vector. Releasing the mouse button ceases force application but preserves existing momentum.
> *   **Parameter Adjustment:** Dragging any slider in the Control Dashboard must immediately update the simulation physics in real-time without requiring a page reload or pause. Increasing viscosity should visibly slow particle separation; increasing gravity should cause faster settling.
> *   **Tool Selection:** Clicking an Emitter Tool button switches the cursor's interaction mode. Selecting "Dye Injector" changes the drag behavior from applying force to adding colored particles. The active tool must remain visually highlighted until another is chosen.
>
> **2. System State Transitions:**
> *   **Initialization Flow:** Upon first load, the simulation remains dormant behind the Initialization Screen. Clicking "Initialize Fluid" dismisses the overlay and starts the physics loop. Particles should emerge from a central source or fill the container gradually.
> *   **Pause/Resume Cycle:** Pressing the Spacebar or clicking a dedicated toggle pauses the physics calculation while maintaining the render loop. The Paused Indicator appears. Resuming continues calculations exactly from the frozen state.
> *   **Reset Behavior:** Activating the Reset button clears all particles and velocity data instantly. Sliders snap back to default positions. The system briefly shows a loading state if re-initialization takes perceptible time.
>
> **3. Responsive Feedback:**
> *   **Cursor Context:** The mouse cursor should change appearance based on the active tool (e.g., crosshair for force, droplet for dye).
> *   **Slider Engagement:** Active sliders should provide tactile visual feedback, such as glow or color shift, during drag operations.
> *   **Boundary Collision:** Particles hitting canvas edges should bounce or slide realistically, providing immediate visual confirmation of boundary constraints.
>
> # web page visual
> This section specifies the aesthetic system, color coding, and typographic standards for the interface.
>
> **1. Design Language:**
> *   **Theme:** "Scientific Instrument" or "Laboratory Clean." The aesthetic should feel precise, calibrated, and uncluttered to emphasize the simulation data.
> *   **Background:** Deep matte charcoal (#1A1A1A) for the page body to reduce eye strain during extended observation. The Fluid Canvas background should be pure black (#000000) to maximize contrast for glowing particles.
>
> **2. Color Palette:**
> *   **Fluid Rendering:** Particles should use additive blending with a gradient mapping based on velocity.
>     *   *Low Velocity:* Cool Cyan (#00FFFF).
>     *   *High Velocity:* Hot Magenta (#FF00FF) or White (#FFFFFF).
> *   **UI Chrome:** Semi-transparent dark grey panels (#2D2D2D with 90% opacity) with subtle 1px borders (#404040).
> *   **Accent Colors:** Electric Blue (#0088FF) for active states, buttons, and slider tracks. Warning Red (#FF4444) reserved solely for performance alerts.
>
> **3. Typography & Hierarchy:**
> *   **Font Family:** A technical sans-serif (e.g., 'Inter', 'Roboto') for UI labels. A monospaced font (e.g., 'JetBrains Mono', 'Fira Code') for all numerical metrics to ensure tabular alignment.
> *   **Scale:** Metric values should be prominent and legible. Slider labels smaller and muted. Instructions minimal and unobtrusive.
>
> **4. Visual Polish:**
> *   **Glow Effects:** Particles must exhibit bloom/glow to simulate light emission. UI elements should have subtle inner shadows for depth.
> *   **Transitions:** All state changes (overlay appearance, color shifts) should use smooth easing to avoid jarring updates.
> *   **Canvas Border:** A thin, subtle border around the simulation area to clearly delineate the interaction zone from the control panel.

页面/文件架构（审计字段，不进入 query）：

- index.html: main simulation viewport and control dashboard

### 5. WC-5 data-workflows

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a data workflow spanning input, analysis, detail, and reporting
- Query 词数：1299
- Seed IDs：WebCompass:text-generation:351, WebCompass:text-generation:505, WebCompass:text-generation:478, WebCompass:text-generation:801

Query：

> # Web page content
> This section defines the structural elements and information architecture for the "YieldStream Precision Agriculture Dashboard," a data workflow application designed to help agronomists analyze soil sensor telemetry, diagnose crop stress factors, and generate field intervention reports. The system comprises four distinct named pages that support a complete analysis-to-action journey.
>
> **1. Global Navigation Shell**
> *   **Persistent Sidebar:** A fixed vertical navigation rail on the left containing links to: Field Overview (Dashboard), Sensor Telemetry (Analysis), Plot Inspector (Detail), and Harvest Reports (Reporting).
> *   **Active State Indicator:** A distinct visual marker highlighting the current page route within the sidebar.
> *   **Global Context Bar:** Displays the currently selected Farm Name and Season Year (e.g., "North Valley Ranch | 2024 Spring"). Includes a global date range picker that persists state across all pages except when explicitly overridden in the Detail view.
> *   **System Status:** A small indicator showing "Live Sync" or "Offline Mode" based on sensor connectivity.
>
> **2. Field Overview (Dashboard Page)**
> *   **Purpose:** High-level health assessment of all managed zones.
> *   **Zone Health Matrix:** A grid of cards representing individual fields. Each card displays a composite "Vigor Score" (0-100) with a color-coded background indicating status (Critical, Warning, Optimal).
> *   **Aggregate KPIs:** Top-row summary metrics showing Average Soil Moisture, Nitrogen Levels, and Predicted Yield vs. Target.
> *   **Alert Feed:** A scrollable list of recent anomalies (e.g., "Irrigation Valve Failure - Zone B3", "Rapid Moisture Drop - Zone A1").
>
> **3. Sensor Telemetry (Analysis Page)**
> *   **Purpose:** Temporal correlation of multi-variate sensor data to identify root causes of stress.
> *   **Variable Selector:** Multi-select checkboxes for Soil Moisture, Temperature, EC (Conductivity), pH, and Solar Radiation.
> *   **Comparative Charting:** A primary time-series visualization overlaying selected variables against historical baselines.
> *   **Anomaly Highlighting:** Automated shading on the chart background where values deviate beyond configured thresholds.
> *   **Correlation Toggle:** A switch to enable/disable statistical regression lines between paired variables (e.g., Temp vs. Moisture).
>
> **4. Plot Inspector (Detail Page)**
> *   **Purpose:** Granular investigation of specific geographic coordinates flagged during analysis.
> *   **Geospatial Context:** A static map tile centered on the specific sensor node with neighboring nodes visible for context.
> *   **Sensor Metadata Card:** Displays installation date, last calibration timestamp, battery level, and firmware version.
> *   **Raw Data Table:** A paginated table showing minute-by-minute readings for the selected time window, with export functionality.
> *   **Annotation Tool:** An input field allowing users to attach qualitative notes to specific timestamps (e.g., "Visual confirmation of fungal infection").
>
> **5. Harvest Reports (Reporting Page)**
> *   **Purpose:** Synthesis of findings into actionable intervention plans.
> *   **Report Builder Wizard:** A step-by-step interface selecting Fields, Time Periods, and Key Metrics to include.
> *   **Preview Pane:** A live-rendered document preview showing charts, tables, and user annotations formatted for print/PDF.
> *   **Recommendation Engine:** Auto-generated text suggestions based on analyzed data (e.g., "Increase irrigation frequency by 15% in Zone B3").
> *   **Distribution Controls:** Options to mark report as "Draft," "Review," or "Finalized."
>
> **Cross-Page User Flows**
> *   **Flow 1: Diagnostic Investigation Journey.** The user identifies a low Vigor Score card on the *Field Overview* page and clicks it. This navigates to the *Sensor Telemetry* page with the specific field pre-filtered and the date range set to the last 7 days. After identifying a moisture deficit correlated with high temperatures, the user clicks a specific anomaly point on the chart. This transitions to the *Plot Inspector* page, zoomed to that exact sensor node and timestamp, displaying raw data and allowing the user to add an annotation confirming equipment failure.
> *   **Flow 2: Intervention Reporting Cycle.** While viewing annotated evidence in the *Plot Inspector*, the user clicks a "Add to Report" action button. This navigates to the *Harvest Reports* page, automatically creating a new draft report populated with the selected chart snapshot and annotation. The user adjusts the recommendation text in the builder, previews the layout, and finalizes the document, which then updates the status badge visible in the global navigation feedback area.
>
> # Web page interaction
> This section specifies the observable behavioral logic, state transitions, and feedback mechanisms governing the user experience without prescribing technical implementation details.
>
> **1. Navigation & State Persistence**
> *   **Context Retention:** When navigating from Analysis to Detail and back to Analysis, all filter selections, zoom levels, and variable toggles must remain exactly as left. Reloading the browser should restore the last active view and filter state.
> *   **Breadcrumb Logic:** Secondary pages (Detail, Reporting) must display clickable breadcrumbs reflecting the navigation path (e.g., Overview > Telemetry > Plot #402). Clicking a parent crumb returns the user to that level with previous filters intact.
> *   **Loading States:** Transitions between pages must show a skeleton screen matching the target layout structure rather than a generic spinner. Data-heavy charts should render progressively, showing axes first, then gridlines, then data points.
>
> **2. Data Interaction Feedback**
> *   **Chart Hover Behavior:** Hovering over any data point in the Telemetry chart must display a tooltip with precise values for all active series at that timestamp. The cursor should change to a crosshair to aid precision alignment.
> *   **Filter Application:** Changing date ranges or variable selections should trigger an immediate optimistic UI update. If data fetching exceeds a brief threshold, a subtle progress bar appears beneath the header. Errors in data retrieval must display inline toast notifications that are dismissible but do not block navigation.
> *   **Annotation Submission:** Saving a note in the Plot Inspector must provide instant visual confirmation (e.g., checkmark icon, green flash) without requiring a page reload. The annotation should immediately appear in the Report Preview if linked.
>
> **3. Workflow Action Feedback**
> *   **Report Generation:** Clicking "Finalize" on a report triggers a multi-stage progress indicator (Validating... Rendering... Complete). Upon success, the user is shown a download option and a "View Final" link.
> *   **Cross-Page Linking:** Clickable elements that bridge pages (e.g., Zone Card to Telemetry) must have distinct hover states indicating interactivity. Active links should show a pressed state on click before navigation completes.
> *   **Form Validation:** In the Report Builder, invalid configurations (e.g., end date before start date) must disable the "Preview" button and display helper text explaining the constraint.
>
> # Web page visual
> This section establishes the aesthetic system, component styling, and visual hierarchy ensuring clarity for data-intensive agricultural workflows.
>
> **1. Color System**
> *   **Background Canvas:** Off-white (#F9FAFB) to reduce glare during extended outdoor/indoor use. Pure white (#FFFFFF) reserved for content cards and panels.
> *   **Primary Brand:** Deep Chlorophyll Green (#2E7D32) used for primary actions, active navigation states, and optimal health indicators.
> *   **Data Semantics:**
>     *   Moisture/Hydration: Cerulean Blue (#0288D1).
>     *   Heat/Temperature: Terracotta Orange (#E65100).
>     *   Nutrients/EC: Amber Gold (#FFA000).
>     *   Critical Alerts: Muted Crimson (#C62828).
>     *   Neutral/Baseline: Slate Gray (#546E7A).
> *   **Chart Palette:** Distinct, accessible colors for each variable series that maintain contrast against both light backgrounds and gridlines.
>
> **2. Typography Hierarchy**
> *   **Headings:** Geometric sans-serif (e.g., Inter, DM Sans). Bold weight for page titles, medium for section headers.
> *   **Data Display:** Monospaced font (e.g., JetBrains Mono, IBM Plex Mono) for all numerical values in tables, KPIs, and tooltips to ensure vertical alignment of digits.
> *   **Body Text:** Clean humanist sans-serif at comfortable reading size with generous line height for annotations and report narratives.
> *   **Labels:** Uppercase tracking for axis labels and metadata keys to distinguish from data values.
>
> **3. Component Styling**
> *   **Cards & Panels:** Subtle border (1px solid #E5E7EB) with minimal shadow elevation. Rounded corners (8px radius) to soften the technical aesthetic.
> *   **Tables:** Zebra striping using alternating very light gray (#F3F4F6) rows. Sticky headers that remain visible during scroll. Right-aligned numerical columns.
> *   **Charts:** Thin gridlines (#E0E0E0) dashed style. Data lines 2-3px weight with smooth interpolation. Interactive points enlarge on hover.
> *   **Buttons:** Primary buttons filled with brand green, white text. Secondary buttons outlined with transparent fill. Consistent padding and border radius across all views.
>
> **4. Visual States**
> *   **Hover:** Cards lift slightly with increased shadow. Links underline. Buttons brighten/darken appropriately.
> *   **Focus:** Visible outline ring (2px offset) in brand color for keyboard accessibility.
> *   **Disabled:** Reduced opacity (0.5) with neutral gray background. Cursor changes to not-allowed.
> *   **Selected/Active:** Filled background tint or bold border in brand color. Persistent until deselected.

页面/文件架构（审计字段，不进入 query）：

- /overview: Zone health matrix and aggregate KPIs for rapid field assessment
- /telemetry: Multi-variable time-series analysis with anomaly detection and correlation tools
- /inspector/:id: Granular sensor detail view with geospatial context and annotation capability
- /reports: Structured report builder combining analyzed data with intervention recommendations

跨页流程（审计字段）：

- User clicks low-vigor zone card on Overview, navigates to pre-filtered Telemetry page, selects anomaly point on chart, and transitions to Plot Inspector with raw data and annotation tool focused on that timestamp
- User adds annotated evidence from Plot Inspector to new draft via action button, navigates to Report Builder with pre-populated content, adjusts recommendations, finalizes document, and sees updated status in global navigation

## WebGen-Bench

### 1. WG-1 commerce-marketplace

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a complete catalog-to-explicit-detail-route-to-cart commerce journey; every referenced detail page must appear in the route architecture
- Query 词数：68
- Seed IDs：WebGen-Bench:train:train_003382, WebGen-Bench:train:train_002981, WebGen-Bench:train:train_003363, WebGen-Bench:train:train_002991

Query：

> Please implement a boutique plant shop website for selling indoor greenery. The website should have functionalities for catalog browsing, product detail viewing, shopping cart management, and checkout processing. Users should be able to explore plants on the homepage, navigate to specific item pages, add products to their cart, and complete purchases through a dedicated checkout page. Use pale green for the background and forest green for UI components.

页面/文件架构（审计字段，不进入 query）：

- homepage: plant catalog display
- product detail: individual plant information
- cart: selected items review
- checkout: payment and order confirmation

跨页流程（审计字段）：

- homepage to product detail to cart to checkout
- cart back to product detail for additional selection

### 2. WG-2 internal-enterprise

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：an enterprise workflow spanning dashboard, records, and settings
- Query 词数：80
- Seed IDs：WebGen-Bench:train:train_001166, WebGen-Bench:train:train_002281, WebGen-Bench:train:train_001858, WebGen-Bench:train:train_002254

Query：

> Please implement an internal vendor compliance portal for tracking supplier certifications. The website should have functionalities for dashboard overview, document verification, and audit settings across connected pages. Users should be able to view compliance status summaries, upload certification documents, approve or reject vendor submissions, and configure notification preferences within the settings panel. The system must link the main dashboard to individual vendor records and administrative configuration screens seamlessly. Use alice blue for the background and dark cyan for UI components.

页面/文件架构（审计字段，不进入 query）：

- dashboard: compliance status overview and alerts
- vendor-records: document upload and verification details
- settings: audit rules and notification configuration

跨页流程（审计字段）：

- dashboard to vendor-records for reviewing specific supplier documents
- vendor-records to settings for adjusting approval workflows

### 3. WG-3 analytics-productivity

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one data-presentation or productivity capability
- Query 词数：58
- Seed IDs：WebGen-Bench:train:train_000841, WebGen-Bench:train:train_005840, WebGen-Bench:train:train_000827, WebGen-Bench:train:train_005680

Query：

> Please implement a project budget tracker for monitoring team spending against allocated limits. The website should have functionalities for displaying cumulative expense charts and category breakdown tables. Users should be able to add new transactions, filter expenses by date range, and view remaining budget balances. Use mint cream for the background and dark slate gray for UI components.

页面/文件架构（审计字段，不进入 query）：

- index.html: main dashboard with chart and table

### 4. WG-4 content-community

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：content presentation combined with one community interaction
- Query 词数：61
- Seed IDs：WebGen-Bench:train:train_001573, WebGen-Bench:train:train_006032, WebGen-Bench:train:train_006125, WebGen-Bench:train:train_000582

Query：

> Please implement a neighborhood plant swap platform for sharing gardening resources locally. The website should have functionalities for listing available cuttings, displaying plant care guides, and arranging exchange meetups. Users should be able to browse local listings, upload their own plant photos, and message other gardeners to coordinate trades. Use mint cream for the background and forest green for UI components.

页面/文件架构（审计字段，不进入 query）：

- index: browse plant listings and care guides
- listing-detail: view specific cutting info and initiate trade

### 5. WG-5 learning-games-media

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one learning, media, or browser-game interaction
- Query 词数：63
- Seed IDs：WebGen-Bench:train:train_001515, WebGen-Bench:train:train_001585, WebGen-Bench:train:train_006579, WebGen-Bench:train:train_006255

Query：

> Please implement a rhythm typing game website that improves keyboard speed through musical interaction. The website should have functionalities for real-time keystroke detection, beat synchronization, and score tracking. Users should be able to select difficulty levels, type falling words in time with background music, and view accuracy statistics after each round. Use midnight blue for the background and neon green for UI components.

页面/文件架构（审计字段，不进入 query）：

- index.html: game menu and difficulty selection
- game.html: active rhythm typing interface
- results.html: post-round accuracy and score display

## Web-Bench

### 1. WB-1 routed-fullstack

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a final routed full-stack product
- Query 词数：415
- Seed IDs：Web-Bench:expressjs:final-project, Web-Bench:nosql:final-project, Web-Bench:sequelize:final-project, Web-Bench:nextjs:final-project

Query：

> Build a complete Next.js veterinary clinic management application named PetCare Portal from scratch using the App Router, node-sqlite3 for persistence, and jose for JWT authentication stored in a cookie named VET_TOKEN with secret PETCARE-SECRET-V1. Do not use third-party UI libraries; implement all styling via custom CSS files. Create a root layout with a fixed header displaying '🐾 PetCare Portal' linking to home and a HeaderAuthMenu component showing a login button for guests or a staff-name dropdown with logout, dashboard, and settings links when authenticated. Include a fixed footer with 'Copyright: PetCare Systems'. Implement routes: '/' displays a welcome message and server-side rendered 'Welcome Dr. {name}!' if logged in, plus navigation to appointments, patients, and admin panels; '/login' handles authentication with role-based redirection; '/appointments' lists upcoming visits in .appointment-card elements with status badges and action buttons; '/appointments/:id' shows full medical history, treatment notes textarea (.treatment-notes-input), prescription form, and .complete-visit-button transitioning status from Scheduled to Completed while deducting service fees from owner balance; '/patients' provides searchable registry with .patient-row entries linking to detail views; '/patients/:id' displays demographics, vaccination records, weight chart placeholder, and .add-medical-record-form; '/dashboard' renders staff-specific metrics including daily appointment count and pending reviews; '/admin/staff' manages employee accounts with role assignment; '/admin/inventory' tracks medical supplies with .restock-button updating quantities. Define libs/db.js connecting to process.env.DB_PATH and libs/schema.sql creating tables for staff, owners, pets, appointments, medical_records, prescriptions, and inventory. Implement APIs: POST /api/auth for login returning role-scoped tokens; GET/POST /api/appointments for scheduling and completion; GET /api/patients with search params; POST /api/medical-records for adding clinical notes; PUT /api/inventory/:item_id for stock adjustments. Ensure cross-route functionality: completing an appointment on /appointments/:id immediately updates the pet's last_visit field visible on /patients/:id and decrements relevant inventory items shown in /admin/inventory. Adding a medical record via .add-medical-record-form on patient details must append to the chronological list without page reload using optimistic UI updates. Enforce strict access control: veterinarians access all clinical data, receptionists only manage appointments and basic patient info, admins handle staff and inventory. All interactive components like HeaderAuthMenu, AppointmentStatusBadge, and InventoryAlert must be vanilla JS in public/components. Handle 404s with custom veterinary-themed message and home link. Maintain consistent CSS class naming including .staff-dashboard, .medical-record-entry, .prescription-form, .inventory-table, and .status-completed throughout the interface. The final codebase must include app/layout.tsx entry point, modular route handlers in app/api/, comprehensive CSS beautifying all specified selectors, and seed data populating three staff members, ten sample pets, and initial inventory levels.

页面/文件架构（审计字段，不进入 query）：

- /: landing page with auth-aware greeting and primary navigation
- /appointments: filterable appointment list with status management
- /appointments/:id: clinical workspace with treatment documentation and visit completion
- /patients/:id: comprehensive pet profile with medical history timeline
- /dashboard: role-specific operational metrics overview
- /admin/inventory: supply management with restock actions

跨页流程（审计字段）：

- Completing appointment on detail page updates pet's last visit timestamp visible on patient profile and decrements inventory counts in admin panel
- Adding medical record on patient detail page appends to chronological list without reload and becomes visible in future appointment context

### 2. WB-2 framework-routing

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a final framework-based product with real routes and shared state
- Query 词数：476
- Seed IDs：Web-Bench:unocss:final-project, Web-Bench:angular:final-project, Web-Bench:tailwind:final-project, Web-Bench:svelte:final-project

Query：

> Build a self-contained Vue 3.4 application using the Composition API and Pinia for state management that implements a volunteer shift coordination platform named 'CivicSync' without external UI libraries or router plugins. Implement a custom hash-based router handling three distinct views: '/dashboard', '/schedule', and '/profile'. The application shell must feature a persistent sidebar navigation with active-state highlighting and a top header displaying the current user's role badge and a global notification bell icon that pulses when unread alerts exist. The Dashboard view at '/' serves as the operational command center, featuring a StatsGrid component with four metric cards showing total volunteers, pending approvals, upcoming shifts, and coverage gaps. Each card must use CSS Grid for internal alignment and display a trend indicator arrow. Below the stats, render an UrgentAlerts list where items have a dismiss button that triggers a slide-up exit animation and updates the global alert count in the header immediately via Pinia store subscription. Include a QuickAction floating button fixed at bottom-right that opens a modal for rapid shift creation; submitting this form must optimistically update the schedule store and navigate to '/schedule' with the new date pre-selected. The Schedule view at '/schedule' displays a weekly grid calendar where columns represent days and rows represent time slots. Each slot cell uses a min-height of 60px and contains assignable volunteer chips styled with role-specific border colors. Implement drag-and-drop functionality using native HTML5 APIs where dragging a volunteer chip from the unassigned pool onto a calendar slot assigns them instantly. If a conflict occurs (double-booking), the cell must flash red and display a tooltip explaining the overlap. Clicking any assigned chip opens a ShiftDetailDrawer sliding in from the right, showing contact info and a 'Release Shift' button that returns the volunteer to the unassigned pool and triggers a warning toast. The Profile view at '/profile' contains a form with validated inputs for name, email, phone, and availability preferences. Use v-model with custom validators ensuring email format and phone length; invalid fields show inline error messages below inputs. Saving changes must persist to localStorage and update the header user badge reactively. Include an AvailabilityMatrix sub-component using a 7x4 CSS Grid where users toggle cells to mark preferred time blocks; selected cells turn green while unavailable cells remain gray. Cross-route synchronization is mandatory: creating a shift via the Dashboard QuickAction modal must reflect immediately on the Schedule view upon navigation, and releasing a shift in the Schedule drawer must decrement the 'upcoming shifts' metric on the Dashboard without page reload. All transitions between routes must use Vue Transition components with fade effects lasting 200ms. Ensure all interactive elements have proper aria-labels and keyboard focus management. The final artifact must be a single App.vue-compatible structure demonstrating precise integration of custom routing, Pinia stores, native drag-and-drop, CSS Grid layouts, and cross-view reactive state updates within a cohesive civic tech interface.

页面/文件架构（审计字段，不进入 query）：

- /dashboard: Operational metrics, urgent alerts, quick shift creation modal
- /schedule: Weekly calendar grid with native drag-and-drop assignment and detail drawer
- /profile: User settings form with validated inputs and visual availability matrix

跨页流程（审计字段）：

- QuickAction modal submission on Dashboard optimistically updates Schedule store and navigates to /schedule with new date context
- Releasing a shift via ShiftDetailDrawer on Schedule decrements Dashboard metric counters reactively through shared Pinia state

### 3. WB-3 document-navigation

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：hierarchical document navigation plus one active table-of-contents behavior; exclude global search, theme switching, and unrelated URL-state systems
- Query 词数：316
- Seed IDs：Web-Bench:sass:final-project, Web-Bench:esmodule:final-project, Web-Bench:bom:final-project, Web-Bench:less:final-project

Query：

> Build a self-contained technical specification viewer using HTML, CSS, and vanilla JavaScript ES modules. The application consists of 'index.html' loading 'styles.css' and 'app.js'. The layout requires a fixed-width '.sidebar' on the left containing a hierarchical '.toc' navigation tree and a scrollable '.main-content' area on the right displaying structured documentation sections. Implement a 'SpecNavigator' class in 'app.js' that parses a hardcoded JSON configuration object defining nested chapters and subsections to dynamically generate both the DOM content blocks and the sidebar tree structure. Each content section must have a unique ID derived from its hierarchy path and include a visible anchor link. The sidebar tree must support recursive rendering with collapsible parent nodes indicated by rotating chevron icons. Clicking a leaf node in the TOC triggers smooth scrolling to the corresponding content section using scrollIntoView with behavior 'smooth'. Implement an 'ActiveSectionObserver' utilizing IntersectionObserver to track visibility of content sections; as the user scrolls, the corresponding TOC item must receive an '.active' class while expanding any collapsed parent branches automatically. The active state must persist correctly during both programmatic navigation and manual scrolling. Include a '.breadcrumb' component above the content area that updates dynamically to reflect the current section's full hierarchy path based on the active observer state. Ensure the sidebar remains sticky during scroll events and highlights hover states distinctly from the active state. All CSS must use custom properties for theming spacing and colors, defined in :root. The implementation must handle edge cases where multiple sections are simultaneously visible by prioritizing the topmost intersecting entry. No external libraries or frameworks are permitted; all tree traversal, observation logic, and DOM manipulation must be native. The final artifact must function as a cohesive single-page documentation reader where navigation state, content rendering, and visual feedback are tightly synchronized through the specified class interfaces and CSS conventions without relying on URL hash changes or browser history API.

页面/文件架构（审计字段，不进入 query）：

- index.html: Single page layout containing sidebar and main content regions
- styles.css: Layout grid, sticky positioning, tree node styling, and active states
- app.js: SpecNavigator class for DOM generation and ActiveSectionObserver for scroll tracking

### 4. WB-4 visual-interactive

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one explicit Canvas, SVG, Three.js, or visual interaction capability
- Query 词数：349
- Seed IDs：Web-Bench:svg-solar:final-project, Web-Bench:canvas:final-project, Web-Bench:pull-loading:final-project, Web-Bench:threejs:final-project

Query：

> Create a self-contained HTML5 Canvas application named waveform-editor implementing a precise audio visualization and region selection tool from scratch. The application must render a single canvas element with id 'viz-canvas' that fills the viewport minus a 60px fixed-height control bar at the bottom. Implement a high-performance rendering loop using requestAnimationFrame that draws a stereo waveform from a generated Float32Array buffer containing 44100 samples per channel. Render the left channel in cyan (#00FFFF) and right channel in magenta (#FF00FF) centered vertically, with amplitude scaling normalized to canvas height. The primary capability is a pixel-accurate drag-to-select interaction: mousedown initiates a selection anchor, mousemove updates a translucent overlay rectangle with class 'selection-region', and mouseup finalizes the time-domain range. During dragging, display vertical cursor lines at start and end points with exact sample indices rendered in a floating tooltip positioned 10px above the cursor. Implement smooth horizontal panning via middle-mouse drag and zooming via mouse wheel centered on the pointer position, clamping zoom level between 1x and 50x. When zoomed beyond 10x, switch rendering from envelope mode to individual sample dots for precision editing. Add a playback head as a red vertical line that advances based on Web Audio API currentTime, pausing automatically when entering selection mode. The bottom control bar must contain three buttons: 'Play/Pause' toggling transport state, 'Clear Selection' resetting the overlay, and 'Export Region' which logs the selected start/end sample indices to console. Ensure the canvas handles window resize events by recalculating device pixel ratio and re-rendering immediately without stretching. All coordinate transformations between screen pixels and audio samples must account for current pan offset and zoom factor using inverse mapping functions. Selection boundaries must snap to zero-crossings when shift key is held during mouseup. Visual feedback includes dimming non-selected regions to 30% opacity and highlighting the active channel on hover. Maintain 60FPS performance even at maximum zoom by implementing viewport culling that only processes visible sample ranges. No external libraries or audio files are permitted; all signal data and interaction logic must be procedurally generated and managed within vanilla JavaScript modules embedded in the single HTML file.

页面/文件架构（审计字段，不进入 query）：

- index.html: Single-file application containing embedded CSS, canvas element, and modular ES6 script blocks for rendering, interaction, and audio state management

### 5. WB-5 core-dom-layout

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one native DOM drag-and-drop capability; CSS layout may support it but must not become a second primary challenge
- Query 词数：340
- Seed IDs：Web-Bench:calculator-files:final-project, Web-Bench:grid:final-project, Web-Bench:dom1:final-project, Web-Bench:dom:final-project

Query：

> Create a single self-contained HTML file named index.html that implements a Kanban-style task management board using native HTML5 Drag and Drop API without external libraries. The document body must have zero margin and use a flexbox layout to fill the viewport with a fixed header (class 'header', height 60px) and a main board container (class 'board') occupying remaining space. The header contains a title element displaying 'Sprint Planner' and an add-task button (id 'add-btn') aligned to the right. Clicking this button prompts for task text and appends a new card element (class 'card') with a unique data-id attribute to the first column. The board displays three vertical columns (class 'column') labeled 'To Do', 'In Progress', and 'Done', each with a distinct pastel background color and fixed width of 320px with 16px gap between them. Each column contains a scrollable card list container (class 'card-list') that fills available height minus the column header. Cards must display task text, have 8px padding, white background, subtle shadow, and cursor grab styling. Implement native drag-and-drop where cards are draggable elements and card-list containers are valid drop targets. During drag operations, the source card must receive class 'dragging' with 0.5 opacity, and valid drop zones must highlight with a dashed border when a draggable enters. Dropping a card onto a card-list appends it to that specific column; dropping directly onto another card inserts the dragged card immediately before the target card in the DOM order. Prevent default browser behaviors during dragover events to allow dropping. Include a delete mechanism: hovering over any card reveals a small delete button (class 'delete-btn') positioned absolutely at top-right; clicking removes the card from DOM. Ensure all state changes reflect immediately in the visual layout without page reload. Use semantic class names exactly as specified: header, board, column, card-list, card, dragging, delete-btn. All JavaScript logic must be embedded in a script tag at document end, utilizing only standard DOM APIs for event handling and manipulation. The interface must remain functional across modern browsers without polyfills or framework dependencies.

页面/文件架构（审计字段，不进入 query）：

- index.html: Complete Kanban board with header, three columns, and embedded drag-and-drop logic

## ArtifactsBench

### 1. AB-1 games

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one distinctive interactive game mechanic
- Query 词数：100
- Seed IDs：ArtifactsBench:benchmark:1036, ArtifactsBench:benchmark:1642, ArtifactsBench:benchmark:8, ArtifactsBench:benchmark:1079

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Make sure the generated code is executable for demonstration. Create a browser-based memory matching game featuring space-themed icon cards. Players must flip cards to find identical pairs within a time limit. The primary mechanic involves smooth card flipping animations and immediate visual feedback when matches occur. Include a simple score counter that updates with each successful pair found. The interface should be clean and responsive for desktop browsers. Ensure all game logic, styling, and assets are contained within a single file for easy testing.

页面/文件架构（审计字段，不进入 query）：

- index.html: Main game container with grid layout and UI overlays

### 2. AB-2 web-applications

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a coherent multi-page web application
- Query 词数：199
- Seed IDs：ArtifactsBench:benchmark:484, ArtifactsBench:benchmark:522, ArtifactsBench:benchmark:533, ArtifactsBench:benchmark:583

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Make sure the generated code is executable for demonstration. Create a community plant care web application. The homepage should display a seasonal planting calendar with interactive cards showing recommended species for the current month. Clicking a plant card navigates to the Plant Encyclopedia page, which lists detailed care profiles including watering frequency, light requirements, and soil type. Each profile must include a 'Add to My Garden' button that saves the plant to the user's personal collection. The My Garden page displays saved plants in a grid layout with visual health status indicators and upcoming care task badges. Clicking a plant here opens the Care Scheduler page, allowing users to log completed tasks like watering or fertilizing and set custom reminder intervals. Implement a simple diagnosis tool on the scheduler page where users can select symptoms from a dropdown to receive basic troubleshooting tips. Ensure all data persists locally so the user journey from discovery to daily maintenance tracking functions seamlessly without a backend. Use mock data for plant species and care instructions to demonstrate the full interaction flow across these four connected pages.

页面/文件架构（审计字段，不进入 query）：

- Home: seasonal planting recommendations and discovery entry point
- Plant Encyclopedia: searchable database with detailed species profiles
- My Garden: personalized dashboard tracking user's saved plant collection
- Care Scheduler: task logging interface with symptom diagnosis tool

跨页流程（审计字段）：

- User discovers seasonal plant on Home, views details in Encyclopedia, and adds to My Garden
- User accesses saved plant from My Garden dashboard to log care tasks and diagnose issues in Scheduler

### 3. AB-3 management-data

- 能力粒度：`compact`
- 页面范围：`unspecified`
- 主要能力：a focused management or data workflow
- Query 词数：105
- Seed IDs：ArtifactsBench:benchmark:850, ArtifactsBench:benchmark:1401, ArtifactsBench:benchmark:498, ArtifactsBench:benchmark:939

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Make sure the generated code is executable for demonstration. Create a volunteer shift coordination dashboard for community food banks that allows administrators to manage volunteer availability, assign shifts based on skills, and track attendance records. The interface should include a calendar view for scheduling, a filterable volunteer roster with contact details, and summary statistics showing coverage gaps. Ensure all data interactions work with mock datasets for immediate testing without backend dependencies. Output as a single HTML file containing necessary styles and scripts to run directly in any modern browser.

页面/文件架构（审计字段，不进入 query）：

- index.html: unified volunteer scheduling and tracking interface

### 4. AB-4 visual-simulation

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one SVG, Canvas, or simulation capability
- Query 词数：89
- Seed IDs：ArtifactsBench:benchmark:150, ArtifactsBench:benchmark:128, ArtifactsBench:benchmark:21, ArtifactsBench:benchmark:102

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Make sure the generated code is executable for demonstration. Please help me implement this SVG visualization using code: an animated wind turbine with rotating blades against a simple horizon line. The blades should spin continuously at a steady pace to simulate energy generation. Include a subtle color shift in the sky background to indicate time passing from day to dusk. Keep the design minimal and scalable without external assets or complex physics engines.

页面/文件架构（审计字段，不进入 query）：

- index.html: Main viewport displaying the animated wind turbine scene

### 5. AB-5 multimedia-utility-other

- 能力粒度：`atomic`
- 页面范围：`unspecified`
- 主要能力：one multimedia, utility, or diagram interaction
- Query 词数：78
- Seed IDs：ArtifactsBench:benchmark:1207, ArtifactsBench:benchmark:1422, ArtifactsBench:benchmark:1378, ArtifactsBench:benchmark:1488

Query：

> You are a code expert. Please use your professional knowledge to generate accurate and professional responses. Make sure the generated code is executable for demonstration. Create a browser-based color palette generator that extracts dominant colors from an uploaded image file. The tool should display the extracted hex codes in a grid layout and allow users to click any swatch to copy its value to the clipboard. Ensure the color extraction logic runs entirely client-side without external API dependencies.

页面/文件架构（审计字段，不进入 query）：

- index.html: main interface with upload area and color grid display

## Vision2Web

### 1. V2W-1 content-community-publishing

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a content, community, or publishing journey
- Query 词数：91
- Seed IDs：Vision2Web:Level2:community_hpe, Vision2Web:Level2:winecompanion, Vision2Web:Level2:forum_vectorworks, Vision2Web:Level2:yeacamp

Query：

> I want to build a VerseCraft poetry publishing platform. When someone opens the site, they see a homepage displaying featured poems and recent community submissions in a grid layout. The global navigation includes links to Discover, Submit, Collections, Workshops, and Profile. Users browse the Discover page to filter verses by theme or form, then click individual entries to view full text on a dedicated reading page. From there, readers navigate to author profiles or submit their own work via the Submit page, which contains a structured composition form and preview toggle.

页面/文件架构（审计字段，不进入 query）：

- homepage: featured poems and recent submissions grid
- discover: filterable verse browsing interface
- reading: full poem display with author link
- submit: structured composition form with preview
- profile: user portfolio and activity history

跨页流程（审计字段）：

- homepage to discover to reading to profile
- navigation to submit to reading preview

### 2. V2W-2 content-knowledge-multimedia

- 能力粒度：`atomic`
- 页面范围：`multi_page`
- 主要能力：one focused cross-page knowledge or multimedia capability
- Query 词数：87
- Seed IDs：Vision2Web:Level2:cosmicshambles, Vision2Web:Level2:teacherserver, Vision2Web:Level2:theaccnz, Vision2Web:Level2:tcm

Query：

> I want to build a SonicAtlas audio archive website. When someone opens the site, they land on a homepage displaying a featured soundscape player and categorized field recording collections. The global navigation includes links to Home, Map, Library, Artists, and Submit. Users browse the Library page to filter recordings by region or instrument, then click an entry to open the Detail page containing waveform visualization, metadata, and embedded playback controls. Navigation between these pages relies on consistent header links and contextual card interactions throughout the browsing experience.

页面/文件架构（审计字段，不进入 query）：

- home: featured player and collection highlights
- library: searchable recording index with filters
- detail: individual track metadata and waveform player
- map: geographic visualization of recording locations

跨页流程（审计字段）：

- homepage to library via category selection
- library to detail page via recording card click

### 3. V2W-3 transaction

- 能力粒度：`comprehensive`
- 页面范围：`multi_page`
- 主要能力：a complete transaction or service journey
- Query 词数：100
- Seed IDs：Vision2Web:Level2:shopnshine, Vision2Web:Level2:oxford-flow, Vision2Web:Level2:maxviewrealty, Vision2Web:Level2:mojarto

Query：

> I want to build a GreenScape landscaping service booking website. When someone opens the site, they see a homepage featuring seasonal service highlights and a prominent quote request form. The global navigation includes links to Services, Portfolio, Pricing, and Contact. From the homepage, clicking a service card leads to a detailed service page describing scope and maintenance requirements. Users then navigate to the booking page to select dates and property size before reaching a confirmation summary. The portfolio page displays completed project galleries accessible via the main menu, allowing users to review past work before returning to the booking flow.

页面/文件架构（审计字段，不进入 query）：

- homepage: seasonal highlights and quote entry
- services: detailed service descriptions
- booking: date and property selection form
- confirmation: appointment summary display
- portfolio: completed project gallery

跨页流程（审计字段）：

- homepage to services to booking to confirmation
- portfolio to booking via navigation menu

### 4. V2W-4 saas

- 能力粒度：`compact`
- 页面范围：`multi_page`
- 主要能力：a SaaS master-detail or dashboard workflow
- Query 词数：89
- Seed IDs：Vision2Web:Level2:casefox, Vision2Web:Level2:wildapricot, Vision2Web:Level2:smartrecruiters, Vision2Web:Level2:anomali

Query：

> I want to build a FleetPulse logistics management dashboard. The global navigation includes Dashboard, Vehicles, Drivers, and Settings. The Dashboard page displays active trip summaries and maintenance alerts with clickable status cards. Selecting a vehicle card navigates to the Vehicle Detail page showing telemetry charts and service history. From there, clicking an assigned driver name opens the Driver Profile page with license documents and shift logs. Users return to the list view via breadcrumb links or the sidebar menu to continue monitoring fleet operations across these connected detail pages.

页面/文件架构（审计字段，不进入 query）：

- Dashboard: active trip summaries and maintenance alerts
- Vehicle Detail: telemetry charts and service history
- Driver Profile: license documents and shift logs

跨页流程（审计字段）：

- Dashboard to Vehicle Detail via status card click
- Vehicle Detail to Driver Profile via driver name link

### 5. V2W-5 public-services

- 能力粒度：`atomic`
- 页面范围：`multi_page`
- 主要能力：one focused public-service application or information flow
- Query 词数：87
- Seed IDs：Vision2Web:Level2:holyoke, Vision2Web:Level2:myimmitracker, Vision2Web:Level2:elections_bc

Query：

> I want to build a Regional Transit Authority website. When someone opens the site, they see a homepage featuring a real-time trip planner widget and service alert banner alongside global navigation for Schedules, Fares, Maps, and Accessibility. Users enter origin and destination details to reach the Trip Results page, which lists available routes with departure times and transfer icons. Selecting a specific option navigates to the Route Detail page showing an interactive stop map and timetable. The Fares page displays pricing tables linked from the main menu.

页面/文件架构（审计字段，不进入 query）：

- home: trip planner widget and service alerts
- trip-results: list of available transit options
- route-detail: interactive stop map and timetable
- fares: pricing tables and pass information

跨页流程（审计字段）：

- homepage trip planner submission to trip results listing
- trip results selection to specific route detail view
