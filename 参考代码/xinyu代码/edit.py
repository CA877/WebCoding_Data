from openai import OpenAI
import os
import json
from typing import List, Dict, Any
from omegaconf import OmegaConf
import shutil
import time
import random
from synthetic.synthesizer import BaseSynthesizer
from utils.config import *
from utils.utils import save_task, chat_with_retry

# ============================================================================
# Task Categories: 4 大类 × 3-4 子类型 = 15 个任务类型
# ============================================================================

# 1. Complex Components (复杂组件)
COMPLEX_COMPONENTS = [
    "Data Table",
    "Rich Text Editor",
    "Drag & Drop Interface",
    "Tree View",
]

# 2. Frontend-Backend Integration (前后端交互)
FRONTEND_BACKEND = [
    "Real-time Dashboard",
    "Infinite Scroll",
    "Async Form Validation",
    "File Upload with Progress",
]

# 3. Advanced Animations (高级动效)
ADVANCED_ANIMATIONS = [
    "Parallax Scrolling",
    "Page Transitions",
    "Particle Effects",
    "Skeleton Loading",
]

# 4. Business Scenarios (综合业务场景)
BUSINESS_SCENARIOS = [
    "Shopping Cart",
    "User Authentication",
    "Multi-step Wizard",
    "Notification Center",
]

# 扁平化任务类型列表
FORWARD_TASKS = (
    COMPLEX_COMPONENTS
    + FRONTEND_BACKEND
    + ADVANCED_ANIMATIONS
    + BUSINESS_SCENARIOS
)

# 每种任务类型的详细说明
TASK_DESCRIPTIONS = {
    # ========== Complex Components ==========
    "Data Table": """Implement an advanced data table component with rich functionality.
    Requirements:
    - Display tabular data with sortable columns (click header to sort asc/desc).
    - Add pagination controls (previous/next, page numbers, items per page selector).
    - Implement column filtering with dropdown or text input per column.
    - Support row selection with checkboxes (single and select-all).
    - Add inline editing capability for editable cells.
    - Responsive design: horizontal scroll or card view on mobile.""",
    "Rich Text Editor": """Implement a WYSIWYG rich text editor component.
    Requirements:
    - Create a toolbar with formatting buttons (Bold, Italic, Underline, Strikethrough).
    - Support heading levels (H1-H3), lists (ordered/unordered), and blockquotes.
    - Implement link insertion with URL input dialog.
    - Add image embedding via URL or placeholder.
    - Use contenteditable div or textarea with preview mode.
    - Sync formatted content to a hidden textarea for form submission.""",
    "Drag & Drop Interface": """Implement a drag-and-drop interface for reordering or organizing items.
    Requirements:
    - Create draggable items with visual drag handles.
    - Implement drop zones with visual feedback (highlight on dragover).
    - Support reordering within a single list (Kanban column style).
    - Add cross-container drag support if multiple lists exist.
    - Show placeholder/ghost element during drag operation.
    - Persist order changes to data structure and optionally localStorage.""",
    "Tree View": """Implement a hierarchical tree view component for nested data.
    Requirements:
    - Display nested items with expand/collapse toggles (arrows or +/- icons).
    - Support multiple levels of nesting (at least 3 levels deep).
    - Implement lazy loading or virtual rendering for large trees.
    - Add checkbox selection with parent-child cascade (select parent selects all children).
    - Support keyboard navigation (arrow keys, Enter to toggle).
    - Add search/filter functionality to highlight matching nodes.""",
    # ========== Frontend-Backend Integration ==========
    "Real-time Dashboard": """Implement a real-time dashboard with live-updating metrics.
    Requirements:
    - Create dashboard cards displaying key metrics (numbers, percentages).
    - Simulate real-time data updates using setInterval or mock WebSocket.
    - Add animated counters that smoothly transition between values.
    - Implement mini charts/sparklines showing trend data (use CSS or canvas).
    - Add status indicators (green/yellow/red) based on thresholds.
    - Include a "last updated" timestamp that refreshes automatically.""",
    "Infinite Scroll": """Implement infinite scroll pagination for a content feed.
    Requirements:
    - Load initial batch of items (e.g., 10-20 items).
    - Detect when user scrolls near bottom using Intersection Observer or scroll event.
    - Fetch and append next batch of items seamlessly.
    - Show loading spinner/skeleton during fetch.
    - Handle end-of-content state with "No more items" message.
    - Implement scroll position restoration on back navigation (optional).""",
    "Async Form Validation": """Implement comprehensive async form validation with server-side checks.
    Requirements:
    - Real-time validation on input blur and form submit.
    - Simulate async validation (e.g., username availability check with delay).
    - Show loading spinner next to field during async validation.
    - Display inline error/success messages with appropriate icons.
    - Debounce rapid input to avoid excessive validation calls.
    - Disable submit button while any async validation is pending.""",
    "File Upload with Progress": """Implement a file upload component with progress tracking.
    Requirements:
    - Create a drag-and-drop zone with click-to-browse fallback.
    - Show file preview (thumbnail for images, icon for others).
    - Display upload progress bar with percentage for each file.
    - Simulate upload progress using XMLHttpRequest or fetch with mock delay.
    - Support multiple file selection and queue management.
    - Add cancel upload and remove file functionality.""",
    # ========== Advanced Animations ==========
    "Parallax Scrolling": """Implement parallax scrolling effects for visual depth.
    Requirements:
    - Create multiple layers that move at different speeds on scroll.
    - Apply parallax to background images, floating elements, or text.
    - Use transform: translate3d for GPU-accelerated smooth performance.
    - Implement both vertical and optional horizontal parallax.
    - Add fade-in/scale effects for elements entering viewport.
    - Ensure graceful degradation on mobile (reduce or disable effects).""",
    "Page Transitions": """Implement smooth page/view transitions for SPA-like experience.
    Requirements:
    - Create animated transitions between different content sections/pages.
    - Implement multiple transition types (fade, slide, zoom, flip).
    - Add enter/exit animations that coordinate timing.
    - Use CSS transitions/animations or Web Animations API.
    - Handle browser back/forward with appropriate reverse animations.
    - Add loading state during content fetch if applicable.""",
    "Particle Effects": """Implement interactive particle effects for visual enhancement.
    Requirements:
    - Create a canvas-based particle system with configurable particle count.
    - Implement particle physics (velocity, gravity, friction, bounce).
    - Add mouse/touch interaction (particles follow cursor, explode on click).
    - Support different particle shapes (circles, squares, custom images).
    - Implement connection lines between nearby particles (constellation effect).
    - Optimize performance with requestAnimationFrame and particle pooling.""",
    "Skeleton Loading": """Implement skeleton loading screens for improved perceived performance.
    Requirements:
    - Create skeleton placeholders matching the layout of actual content.
    - Add shimmer/pulse animation effect on skeleton elements.
    - Implement skeletons for various content types (text, images, cards, lists).
    - Smooth transition from skeleton to actual content when loaded.
    - Support different skeleton variants based on content type.
    - Ensure skeletons are accessible (aria-busy, aria-label).""",
    # ========== Business Scenarios ==========
    "Shopping Cart": """Implement a fully functional shopping cart system.
    Requirements:
    - Add "Add to Cart" buttons on product items with quantity selector.
    - Create cart sidebar/dropdown showing added items with thumbnails.
    - Implement quantity adjustment (+/-) and remove item functionality.
    - Calculate and display subtotal, tax, and total in real-time.
    - Persist cart data in localStorage across page refreshes.
    - Add cart badge showing item count on cart icon.""",
    "User Authentication": """Implement a complete user authentication UI flow.
    Requirements:
    - Create login form with email/username and password fields.
    - Create registration form with password confirmation and terms checkbox.
    - Implement "Forgot Password" flow with email input.
    - Add form validation with appropriate error messages.
    - Show/hide password toggle functionality.
    - Simulate auth state with localStorage and update UI accordingly (logged in/out).""",
    "Multi-step Wizard": """Implement a multi-step form wizard with progress tracking.
    Requirements:
    - Create a step indicator showing current step and total steps.
    - Implement step navigation (Next, Previous, Skip if allowed).
    - Validate each step before allowing progression.
    - Show step completion status (completed, current, upcoming).
    - Persist form data across steps (don't lose data on back navigation).
    - Add final review step showing all entered data before submission.""",
    "Notification Center": """Implement a notification center with real-time alerts.
    Requirements:
    - Create notification bell icon with unread count badge.
    - Implement dropdown panel showing notification list.
    - Support different notification types (info, success, warning, error).
    - Add mark as read (individual and mark all) functionality.
    - Implement notification grouping by date or type.
    - Add simulated real-time notifications using setInterval or mock events.""",
}


class EditTaskSynthesizer(BaseSynthesizer):

    def generate_forward_task(
        self, generation_data: Dict, task_types: List[str]
    ) -> Dict:
        """
        前向演化 - 仅生成高难度开发需求描述（不生成 search/replace 代码）

        Args:
            generation_data: 原始 generation 数据
            task_types: 任务类型列表

        Returns:
            包含 task_type 和 description 的字典，不包含 dst_code
        """
        src_code = generation_data["dst_code"]
        src_code_context = self.format_code_context(src_code)

        # 构建多任务描述，为每个任务编号
        task_descriptions_str = ""
        for idx, t_type in enumerate(task_types, 1):
            desc = TASK_DESCRIPTIONS.get(t_type, "")
            task_descriptions_str += (
                f"Task {idx}: {t_type}\n  Guideline: {desc}\n\n"
            )
        task_types_json = json.dumps(task_types, ensure_ascii=False)
        prompt = f"""You are an expert web developer creating a challenging web development task dataset.

I have an existing webpage codebase. Based on this code, generate {len(task_types)} detailed development requirement(s) that would be challenging yet realistic for a developer to implement.

Tasks to generate requirements for:
{task_descriptions_str}

IMPORTANT GUIDELINES:
1. **Context-Aware**: Each requirement must be tailored to the existing website's theme, style, and purpose. Don't generate generic requirements.
2. **Specific & Detailed**: Describe exactly what needs to be built, including UI elements, interactions, and expected behaviors.
3. **Challenging but Realistic**: Requirements should push developer skills but remain achievable within the existing codebase structure.
4. **No Implementation Details**: Do NOT mention specific CSS class names, IDs, or exact code snippets. Describe the "what" not the "how".
5. **User-Centric Language**: Write requirements as if briefing a developer, focusing on user experience and functionality.

Return XML format with the following structure:
<description>
[
  {{"task_type": "ExactTaskType 1", "description": "Detailed requirement description for task 1..."}},
  {{"task_type": "ExactTaskType 2", "description": "Detailed requirement description for task 2..."}},
  ...
]
</description>

**CRITICAL - task_type MUST be EXACTLY one of these values (copy verbatim):**
{task_types_json}

Do NOT use synonyms, variations, or placeholder names like "Task Type 1".
Each task_type in your response MUST exactly match one of the provided task types above.

Example of GOOD description:
{{"task_type": "Shopping Cart", "description": "Implement a shopping cart for this e-commerce site. Add 'Add to Cart' buttons below each product card in the product grid. Create a slide-out cart panel from the right side showing item thumbnails, names, prices, and quantity controls. Display a running total at the bottom with a 'Checkout' button. The cart icon in the header should show a badge with the current item count. Cart contents should persist across page refreshes."}}

Example of BAD description (too generic/technical):
{{"task_type": "Shopping Cart", "description": "Add a cart using localStorage. Create a div with class cart-panel and add click handlers."}}

Example of INVALID task_type (DO NOT DO THIS):
{{"task_type": "ExactTaskType 1", ...}}  <- WRONG: placeholder name
{{"task_type": "Data Grid", ...}}    <- WRONG: synonym of "Data Table"
{{"task_type": "shopping cart", ...}} <- WRONG: wrong case

Here is the existing source code to analyze:
{src_code_context}"""

        messages = [
            {
                "role": "system",
                "content": "You are a senior product manager creating detailed, challenging web development requirements in XML format.",
            },
            {"role": "user", "content": prompt},
        ]

        try:
            # 使用带重试的生成方法
            result = self._generate_description_with_retry(
                messages=messages,
                max_retries=self.max_retries,
                expected_task_types=task_types,
            )

            return {
                "task": "edit",
                "task_type": task_types,
                "description": result["description"],
                "src_code": src_code,
                "dst_code": [],
                "resources": generation_data.get("resources", []),
                "label_modified_files": [],
                "synthetic_modified_files": [],
                "llm_raw_response": result["raw_response"],
                "llm_metadata": result["llm_metadata"],
            }
        except Exception as e:
            print(f"Error generating forward task ({task_types}): {e}")
            import traceback

            traceback.print_exc()
            return None

    def process_single_generation_entry(
        self,
        generation_entry: Dict,
        output_dir: str = None,
        folder_name: str = None,
        source_generation_dir: str = None,
        task_types: List[str] = FORWARD_TASKS,
        difficulty_levels: List[int] = None,
        level_range: tuple = None,
        num_levels: int = None,
    ) -> List[Dict]:
        """
        处理单个 generation entry，为每种难度级别生成编辑任务

        Args:
            generation_entry: 原始 generation 数据
            output_dir: 输出目录
            folder_name: 文件夹名称
            source_generation_dir: 源 generation 目录
            task_types: 可选的任务类型列表，默认为所有类型
            difficulty_levels: 难度等级列表，表示每个任务包含的修改数量
            level_range: 难度等级范围 (min_level, max_level)
            num_levels: 从 level_range 中不放回采样的数量
        """
        generated_tasks = []
        task_index = 0

        # Filter tasks based on resources
        resources_info = generation_entry["resources"]
        has_images = any(r.get("type") == "image" for r in resources_info)

        available_task_types = list(task_types)
        # 移除不适用的任务类型
        if not has_images:
            for task in ["Parallax Scrolling"]:
                if task in available_task_types:
                    available_task_types.remove(task)

        if not available_task_types:
            print(f"Skipping {folder_name}: No valid task types available.")
            return []

        # 生成本条数据的 difficulty_levels（每条数据独立采样）
        if difficulty_levels is None and level_range and num_levels:
            min_level, max_level = level_range
            max_level = min(max_level, len(available_task_types))
            if min_level > max_level:
                print(
                    f"Skipping {folder_name}: level_range {level_range} exceeds available task types ({len(available_task_types)})."
                )
                return []
            candidate_levels = list(range(min_level, max_level + 1))
            # k = min(num_levels, len(candidate_levels))
            difficulty_levels = random.choices(candidate_levels, k=num_levels)

        if difficulty_levels is None:
            difficulty_levels = [1]

        # 遍历每个难度等级（即每个任务包含的修改数量）
        for level in difficulty_levels:
            if level > len(available_task_types):
                print(
                    f"Warning: Level {level} exceeds available task types ({len(available_task_types)}), using max available."
                )
                level = len(available_task_types)

            # 随机抽取 level 个任务（不允许重复）
            selected_types = random.sample(available_task_types, k=level)

            print(f"Generating Forward Task (Level {level}): {selected_types}")
            task = self.generate_forward_task(generation_entry, selected_types)

            if task:
                generated_tasks.append(task)
                # 立即保存
                if output_dir and folder_name:
                    # 文件名包含难度等级
                    task_id = f"{folder_name}_L{level}_{task_index}"
                    save_task(
                        task,
                        output_dir,
                        task_id,
                        source_generation_dir=source_generation_dir,
                        resources_info=resources_info,
                        skip_dst=True,  # 不生成 dst 目录和截图
                    )
                task_index += 1

        return generated_tasks


def main(max_workers=4,input_dir=None, output_dir=None, difficulty_levels=None, level_range=None, num_levels=None, max_retries=3):
    """
    主函数 - 多线程版本

    Args:
        max_workers: 最大线程数
        input_dir: 输入目录路径
        difficulty_levels: 难度等级列表，例如 [1, 2, 3] 表示分别生成包含1个、2个、3个修改的任务
        level_range: 难度等级范围 (min_level, max_level)
        num_levels: 从 level_range 中不放回采样的数量
    """
    config = OmegaConf.load("config/api.yaml")
    api_key = config.api.api_key
    base_url = config.api.base_url
    model = "gemini-3-pro-preview"

    synthesizer = EditTaskSynthesizer(
        api_key, base_url, model, max_tokens=64 * 1024, max_retries=max_retries
    )

    if difficulty_levels is None and level_range and num_levels:
        print(f"Sampling levels per entry from range {level_range}, num={num_levels}")
    elif difficulty_levels is None:
        difficulty_levels = [1, 2]  # 默认生成 1, 2 种复杂修改组合的任务

    print(f"Generating tasks with difficulty levels: {difficulty_levels}")

    synthesizer.run_batch_processing(
        input_dir=input_dir,
        output_dir=output_dir,
        max_workers=max_workers,
        task_types=FORWARD_TASKS,
        difficulty_levels=difficulty_levels,
        level_range=level_range,
        num_levels=num_levels,
    )


def test_single_generation(
    generation_folder: str,
    output_dir: str = None,
    task_types: List[str] = None,
    difficulty_levels: List[int] = None,
    level_range: tuple = None,
    num_levels: int = None,
) -> List[Dict]:
    """
    测试函数:处理指定的单个 generation 文件夹

    Args:
        generation_folder: generation 文件夹的路径
        output_dir: 输出目录,如果为 None 则不保存文件,只返回结果
        task_types: 要生成的前向任务类型列表，默认为所有类型
        difficulty_levels: 难度等级列表，例如 [1, 2, 3] 表示分别生成包含1个、2个、3个修改的任务
        level_range: 难度等级范围 (min_level, max_level)
        num_levels: 从 level_range 中不放回采样的数量

    Returns:
        生成的 edit task 列表

    Example:
        # 只生成不保存
        tasks = test_single_generation("/path/to/generation/folder")

        # 生成并保存，只测试部分任务类型
        tasks = test_single_generation(
            "/path/to/generation/folder",
            "/path/to/output",
            task_types=["Data Table"]
        )
    """
    config = OmegaConf.load("config/api.yaml")
    api_key = config.api.api_key
    base_url = config.api.base_url
    model = "gpt-5-codex"
    synthesizer = EditTaskSynthesizer(
        api_key, base_url, model, max_tokens=16 * 1024, max_retries=6
    )

    # 模拟 process_single_generation_entry 的调用逻辑
    info_path = os.path.join(generation_folder, "info.json")
    with open(info_path, "r", encoding="utf-8") as f:
        gen_data = json.load(f)

    return synthesizer.process_single_generation_entry(
        gen_data,
        output_dir=output_dir,
        folder_name=os.path.basename(generation_folder),
        source_generation_dir=generation_folder,
        task_types=task_types or FORWARD_TASKS,
        difficulty_levels=difficulty_levels,
        level_range=level_range,
        num_levels=num_levels,
    )


if __name__ == "__main__":
    framework_list = ["react", "vue", "angular"]
    page_category_list = ["sp", "mp"]
    base_dir = "/root/bayes-tmp/data/webcoding_framework_dataset_test"
    for framework in framework_list:
        for page_category in page_category_list:
            input_dir = f"{base_dir}/{framework}/{page_category}/generation"  # 可以替换为 react/vue 或 mp 目录进行测试
            output_dir = f"{base_dir}/{framework}/{page_category}/edit"
            main(max_workers=16, input_dir=input_dir, output_dir=output_dir, level_range=(4, 12), num_levels=1, max_retries=6)

    # # 或者测试单个文件夹
    # tasks = test_single_generation(
    #     "/Users/pedestrian/Desktop/web_coding_output/data/data_demo_renderbench_3_6_9/generation/2930611_www.fieldsquared.com",
    #     "/Users/pedestrian/Desktop/web_coding_output/data/data_demo_renderbench_3_6_9/edit_test_multi",
    #     task_types=FORWARD_TASKS,
    #     difficulty_levels=[3, 6, 9],
    # )
