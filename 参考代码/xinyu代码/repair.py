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
from utils.utils import save_task

# 破坏类型分类
DEFECT_TYPES = [
    "Occlusion",           # 遮挡
    "Crowding",            # 拥挤
    "Text Overlap",        # 文本重叠
    "Alignment",           # 对齐问题
    "Color Contrast",      # 颜色与对比度
    "Overflow",            # 溢出
    "Sizing Proportion",   # 尺寸/比例失衡
    "Loss of Interactivity",  # 交互性丧失
    "Semantic Error",      # 语义错误
    "Nesting Error",       # 嵌套错误
    "Missing Attributes",  # 属性缺失
]

# 每种破坏类型的详细说明
DEFECT_DESCRIPTIONS = {
    "Occlusion": """Increase the z-index of element A so that it covers element B. 
    For example, make a modal overlay cover important content, or make a fixed header cover interactive elements.""",
    
    "Crowding": """Remove margin or padding between elements A and B, or shrink their parent container size.
    For example, remove spacing between navigation items, or collapse the gap between form fields.""",
    
    "Text Overlap": """Reduce the width or line-height of a text container, or position two text containers at the same location.
    For example, make text overflow its container and overlap with adjacent elements.""",
    
    "Alignment": """Adjust the left/top properties of element A so it's not aligned with the grid or sibling element B.
    For example, misalign navigation items, or offset a button from its expected position.""",
    
    "Color Contrast": """Set text color to a value similar to the background color (e.g., light gray text on white background).
    For example, make body text nearly invisible, or reduce contrast of important labels.""",
    
    "Overflow": """Add excessive content to a fixed height/width container and set overflow: visible or remove overflow handling.
    For example, add too much text to a card component causing it to break layout.""",
    
    "Sizing Proportion": """Set an image to extreme dimensions (e.g., width: 10px, height: 200px), or make a container unnecessarily huge.
    For example, distort an image aspect ratio, or make a small icon take up entire width.""",
    
    "Loss of Interactivity": """Disable a button element, or use CSS pointer-events: none to make a link unclickable.
    For example, add disabled attribute to submit button, or block clicks on navigation links.""",
    
    "Semantic Error": """Replace heading <h1> element with <div> element styled the same way.
    For example, convert semantic nav to div, or replace button with styled span.""",
    
    "Nesting Error": """Place an <a> tag inside another <a> tag, or put a <div> inside a <p> tag.
    For example, nest block elements inside inline elements incorrectly.""",
    
    "Missing Attributes": """Remove alt attribute from <img> elements, or remove aria-label from form inputs.
    For example, remove accessibility attributes, or remove required form attributes.""",
}


class RepairTaskSynthesizer(BaseSynthesizer):
    def generate_defect_task(self, generation_data: Dict, defect_types: List[str]) -> Dict:
        """
        逆向生成策略：支持多缺陷注入
        现有代码(Generation) -> 目标代码（正确的结果）
        LLM注入缺陷 -> 源代码（需要修复的代码）
        """
        dst_code = generation_data["dst_code"]
        dst_code_context = self.format_code_context(dst_code)
        
        # 构建多缺陷描述，为每个缺陷编号
        defect_descriptions_str = ""
        for idx, d_type in enumerate(defect_types, 1):
            desc = DEFECT_DESCRIPTIONS.get(d_type, "")
            defect_descriptions_str += f"Defect {idx}: {d_type}\n  Guideline: {desc}\n\n"

        # 将 defect_types 转为 JSON 字符串用于 prompt
        defect_types_json = json.dumps(defect_types, ensure_ascii=False)

        prompt = f"""You are an expert web developer. I have a clean, high-quality codebase for a webpage.
I want to generate a dataset for web repair/debugging tasks.

You need to inject {len(defect_types)} defect(s) in total:

{defect_descriptions_str}

Please analyze the provided code and inject specific defects for EACH defect type listed above.
The defects should be realistic and something that could occur during development.
Then, implement ALL the defect injections using search/replace blocks.

Return XML format with the following structure:
<description>
[
  {{"task_type": "ExactDefectTypeName1", "description": "Description for Defect 1"}},
  {{"task_type": "ExactDefectTypeName2", "description": "Description for Defect 2"}},
  ...
]
</description>
<search_replace path="path/to/file">
<search>
exact text to find in the original file
</search>
<replace>
replacement text with the defect injected
</replace>
</search_replace>

**CRITICAL - task_type values MUST be EXACTLY from this list (copy verbatim, preserve exact spelling and case):**
{defect_types_json}

Do NOT use:
- Placeholder names like "Defect Type 1", "Task Type 2", "Type 1"
- Synonyms or variations (e.g., "Z-Index Issue" instead of "Occlusion")
- Different capitalization (e.g., "occlusion" instead of "Occlusion")

Each task_type in your response MUST exactly match one of the defect types listed above.

Important for <description>:
- Provide a JSON array with ONE object for EACH defect (total {len(defect_types)} objects).
- Each object must have exactly two fields: "task_type" and "description".
- The "task_type" MUST be copied exactly from the list above.
- The "description" must be a repair instruction that clearly identifies the issue or the target element (e.g., by its text content, position, or unique feature) so the intent is unambiguous.
- However, it must NOT reveal the exact code implementation details (e.g., do not mention specific class names, ID selectors, or exact CSS property values unless they are part of the requirement).
Example of GOOD description:
{{"task_type": "Occlusion", "description": "Fix the 'Submit' button being covered by the footer"}}
Example of BAD description (too generic/technical):
{{"task_type": "Occlusion", "description": "Change z-index of .footer to -1"}}
Example of INVALID task_type (DO NOT DO THIS):
{{"task_type": "Defect 1", ...}}           <- WRONG: placeholder
{{"task_type": "Defect Type 1", ...}}      <- WRONG: placeholder  
{{"task_type": "Z-Index Problem", ...}}    <- WRONG: should be "Occlusion"
{{"task_type": "occlusion", ...}}          <- WRONG: wrong case, should be "Occlusion"
{{"task_type": "Contrast Issue", ...}}     <- WRONG: should be "Color Contrast"

Important for <search_replace>:
- You MUST implement defect injections for ALL {len(defect_types)} defect types.
- The <search> block must contain the EXACT text from the original file (including whitespace and indentation).
- The <search> text MUST be unique and match exactly once in the file - avoid generic patterns that could match multiple locations.
- The <replace> block contains the modified code with the defect injected.
- One <search_replace> block can only contain one pair of <search> and <replace>.
- You can include multiple <search_replace> blocks if you need to modify multiple locations, you can also modify multiple files.


Here is the clean code (which will be the Goal/Dst state after repair):
{dst_code_context}"""
        try:
            result = self._generate_and_apply_with_retry(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that generates web development debugging datasets in XML format using search/replace blocks.",
                    },
                    {"role": "user", "content": prompt},
                ],
                code_list=dst_code,
                max_retries=self.max_retries,
                expected_task_types=defect_types,  # 传递期望的 task_types 用于验证
            )

            # src_code 是注入缺陷后的代码（需要修复的起始状态）
            src_code = result["modified_code"]
            
            label_modified_files = []
            for mod in result.get("modified_files", []):
                label_modified_files.append({
                    "path": mod["path"],
                    "search": mod["replace"],
                    "replace": mod["search"],
                })
            return {
                "task": "repair",
                "task_type": defect_types,
                "description": result["description"],
                "src_code": src_code,  # 有缺陷的代码
                "dst_code": dst_code,  # 正确的代码
                "resources": generation_data.get("resources", []),
                "label_modified_files": label_modified_files,  # 训练时src2dst时应该使用的modified_files
                "synthetic_modified_files": result.get("modified_files", []),  # 合成数据时进行修改的文件
                "llm_raw_response": result.get("raw_response"),
                "llm_metadata": result.get("llm_metadata"),
            }
        except Exception as e:
            print(f"Error generating defect task ({defect_types}): {e}")
            import traceback
            traceback.print_exc()
            return None
        
    def process_single_generation_entry(
        self,
        generation_entry: Dict,
        output_dir: str = None,
        folder_name: str = None,
        source_generation_dir: str = None,
        task_types: List[str] = DEFECT_TYPES,
        difficulty_levels: List[int] = None,
        level_range: tuple = None,
        num_levels: int = None,
    ) -> List[Dict]:
        """
        处理单个 generation entry，为每种难度级别生成修复任务
        
        Args:
            generation_entry: 原始 generation 数据
            output_dir: 输出目录
            folder_name: 文件夹名称
            source_generation_dir: 源 generation 目录
            task_types: 要生成的缺陷类型列表，默认为所有类型
            difficulty_levels: 难度等级列表，表示每个任务包含的缺陷数量
            level_range: 难度等级范围 (min_level, max_level)
            num_levels: 从 level_range 中不放回采样的数量
        """
        generated_tasks = []
        task_index = 0
        resources_info = generation_entry["resources"]
        # 生成本条数据的 difficulty_levels（每条数据独立采样）
        if difficulty_levels is None and level_range and num_levels:
            min_level, max_level = level_range
            if min_level > max_level:
                print(
                    f"Skipping {folder_name}: level_range {level_range} exceeds available task types ({len(task_types)})."
                )
                return []
            candidate_levels = list(range(min_level, max_level + 1))
            # k = min(num_levels, len(candidate_levels))
            difficulty_levels = random.choices(candidate_levels, k=num_levels)

        if difficulty_levels is None:
            difficulty_levels = [1]

        # 遍历每个难度等级（即每个任务包含的缺陷数量）
        for level in difficulty_levels:
            # 随机抽取 level 个缺陷类型（允许重复）
            selected_types = random.choices(task_types, k=level)
            
            print(f"Generating Repair Task (Level {level}): {selected_types}")
            task = self.generate_defect_task(generation_entry, selected_types)
            
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
                        resources_info = resources_info,
                    )
                task_index += 1

        return generated_tasks


def main(max_workers=4,input_dir=None, output_dir=None, difficulty_levels=None, level_range=None, num_levels=None, max_retries=3):
    """
    主函数 - 多线程版本
    
    Args:
        max_workers: 最大线程数
        input_dir: 输入目录路径
        output_dir: 输出目录路径
        difficulty_levels: 难度等级列表，例如 [1, 2, 3] 表示分别生成包含1个、2个、3个缺陷的任务
        level_range: 难度等级范围 (min_level, max_level)
        num_levels: 从 level_range 中不放回采样的数量
    """
    # Configuration
    config = OmegaConf.load("config/api.yaml")
    api_key = config.api.api_key
    base_url = config.api.base_url
    # model = "gpt-5-codex"
    model = "gemini-3-pro-preview"

    synthesizer = RepairTaskSynthesizer(api_key, base_url, model, max_tokens=64*1024, max_retries=max_retries)

    if difficulty_levels is None and level_range and num_levels:
        print(f"Sampling levels per entry from range {level_range}, num={num_levels}")
    elif difficulty_levels is None:
        difficulty_levels = [1, 2, 3]  # 默认生成 1, 2, 3 种缺陷组合的任务

    print(f"Generating tasks with difficulty levels: {difficulty_levels}")

    synthesizer.run_batch_processing(
        input_dir=input_dir,
        output_dir=output_dir,
        max_workers=max_workers,
        task_types=DEFECT_TYPES,
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
        task_types: 要生成的缺陷类型列表，默认为所有类型
        difficulty_levels: 难度等级列表, 默认为 [1, 2]
        level_range: 难度等级范围 (min_level, max_level)
        num_levels: 从 level_range 中不放回采样的数量
    """
    config = OmegaConf.load("config/api.yaml")
    api_key = config.api.api_key
    base_url = config.api.base_url
    model = "gemini-3-pro-preview"
    synthesizer = RepairTaskSynthesizer(api_key, base_url, model, max_tokens=64*1024, max_retries=6)

    # 模拟 process_single_generation_entry 的调用逻辑
    info_path = os.path.join(generation_folder, "info.json")
    with open(info_path, "r", encoding="utf-8") as f:
        gen_data = json.load(f)

    return synthesizer.process_single_generation_entry(
        gen_data,
        output_dir=output_dir,
        folder_name=os.path.basename(generation_folder),
        source_generation_dir=generation_folder,
        task_types=task_types,
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
            output_dir = f"{base_dir}/{framework}/{page_category}/repair"
            main(max_workers=16, input_dir=input_dir, output_dir=output_dir, level_range=(4, 12), num_levels=1, max_retries=6)
            
    # # 或者测试单个缺陷类型
    # task = test_single_generation(
    #     "/Users/pedestrian/Desktop/web_coding_output/data/data_demo_renderbench_10/generation/1009769_www.kccworld.co.kr_english_",
    #     "/Users/pedestrian/Desktop/web_coding_output/data/data_demo_renderbench_10/repair_test_multi",
    #     task_types=DEFECT_TYPES,
    #     difficulty_levels=[8],
    # )