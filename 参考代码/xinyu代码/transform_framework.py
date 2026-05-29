import base64
from openai import OpenAI
import os
import json
import shutil
from omegaconf import OmegaConf
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
from utils.config import *


def transform_generation(
    dataset_base_path: str, web_name: str, output_folder: str
):
    """
    Transforms HTML files in the specified directory into a JSONL format suitable for LLM training.

    Args:
        web_name (str): Name of the webpage.
        output_folder (str): Path to the output folder.
    """
    info = {
        "task": "generation",
        "task_type": ["multi page", "with resource"],
        "description": "",
        "dst_screenshot": [],
        "dst_code": [],
        "resources": [],
    }
    dstcode_count = 0
    screenshot_count = 0
    webpage_folder = os.path.join(dataset_base_path, web_name)
    os.makedirs(output_folder, exist_ok=True)
    dst_repo_dir = os.path.join(output_folder, "dst")
    os.makedirs(dst_repo_dir, exist_ok=True)

    for root, dirs, files in os.walk(webpage_folder):
        dirs.sort()
        files.sort()

        for filename in files:
            # 忽略系统文件：不拷贝、不记录
            if filename in IGNORE_FILE:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, webpage_folder).replace(os.sep, "/")
            file_ext = os.path.splitext(filename)[1].lower()

            # 拷贝所有未忽略文件到 dst，保持相对路径结构
            dst_file_path = os.path.join(dst_repo_dir, rel_path)
            os.makedirs(os.path.dirname(dst_file_path), exist_ok=True)
            shutil.copy2(file_path, dst_file_path)

            # package.json 特判：作为 resources 而不是 code
            if filename.lower() == "package.json":
                info["resources"].append(
                    {
                        "type": "other",
                        "path": rel_path,
                        "description": "",
                    }
                )
            # 代码文件写入 dst_code
            elif file_ext in CODE_EXTENSIONS:
                with open(file_path, "r", encoding="utf-8") as f:
                    code_content = f.read()
                info["dst_code"].append(
                    {
                        "path": rel_path,
                        "code": code_content,
                    }
                )
                dstcode_count += 1
            # 非代码文件写入 resources
            elif file_ext in IMAGE_EXTENSIONS:
                info["resources"].append(
                    {
                        "type": "image",
                        "path": rel_path,
                        "description": "",
                    }
                )
            else:
                info["resources"].append(
                    {
                        "type": "other",
                        "path": rel_path,
                        "description": "",
                    }
                )

    # 无截图，描述置空
    info["description"] = ""

    # 写入输出文件
    info_file = os.path.join(output_folder, "info.json")
    with open(info_file, "w", encoding="utf-8") as out_f:
        json.dump(info, out_f, ensure_ascii=False, indent=4)

    print(f"Successfully generated description and saved to {info_file}")


if __name__ == "__main__":
    framework_list = [
        "angular",
        "react",
        "vue",
    ]
    output_dir = "/root/bayes-tmp/data/webcoding_framework_dataset"
    web_number = 100
    for framework in framework_list:
        for web_page_category in ["sp", "mp"]:
            if web_page_category == "sp":
                dataset_base_path = f"/root/bayes-tmp/data/webcoding_framework_raw/htmlto{framework}/filter_{framework}_50"  # 数据集文件夹路径
            elif web_page_category == "mp":
                dataset_base_path = f"/root/bayes-tmp/data/webcoding_framework_raw/htmlto{framework}/filter_mp_{framework}_50"  # 数据集文件夹路径
            # 直接读取dataset_base_path下的所有文件夹
            web_names = sorted(os.listdir(dataset_base_path))
            web_names = web_names[:web_number]  # 限制数量
            for web_name in web_names:
                
                web_path = os.path.join(dataset_base_path, web_name)
                if not os.path.isdir(web_path):
                    continue
                output_folder = f"{output_dir}/{framework}/{web_page_category}/generation/{web_name}"
                transform_generation(
                    dataset_base_path, web_name, output_folder
                )
