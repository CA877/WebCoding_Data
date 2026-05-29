import base64
from openai import OpenAI
import os
import json
import shutil
from omegaconf import OmegaConf
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import encode_image, chat_with_retry, get_image_mime_type
import traceback
from utils.config import *
# 统一使用的模型
MODEL_NAME = "gpt-4o-mini"



description_prompt_mapping = {
    "generation": '**Role:**\nYou are a senior Frontend Product Manager and UI Designer. Please analyze the provided webpage screenshot to generate a concise requirement description for frontend development.\n\n**Task:**\nAnalyze the provided screenshot and summarize the webpage\'s core visual characteristics and key interactions using **very concise natural language (under 150 words)**.\n\n**Strict Rules:**\n- **Zero Code Principle:** Do NOT use any code snippets, HTML tags, or technical CSS parameters.\n- **Visuals Only:** Describe only what a user can "see" and "feel." For example, instead of saying "set border-radius to 50%," say "the avatar is displayed as a perfect circle."\n- **Macro Perspective:** Focus on the overall layout (Header/Body/Footer), the primary color palette/mood, the visual style, and the core functional components (e.g., forms, buttons, input fields).\n\n**Goal:**\nThe description must be clear enough to guide a frontend developer in implementing the design.\n\n',
}


def get_image_description(client: OpenAI, file_path: str, filename: str):
    """获取单个图片的描述"""
    base64_image = encode_image(file_path)
    
    # 根据文件扩展名确定MIME类型
    mime_type = get_image_mime_type(file_path)
    
    image_description_message = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Please describe this image briefly in 1-2 sentences, focusing on its visual content and purpose.",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_image}"
                    },
                },
            ],
        }
    ]

    description = chat_with_retry(
        client=client,
        messages=image_description_message,
        model=MODEL_NAME,
        max_tokens=200,
        temperature=0.7,
        max_retries=6
    )

    return {
        "type": "image",
        "path": f"resources/{filename}",
        "description": description if description else "",
    }


def transform_generation(
    client: OpenAI, dataset_base_path: str, web_name: str, output_folder: str
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

    resources_data_dir = os.path.join(webpage_folder, "resources")
    resources_dst = os.path.join(dst_repo_dir, "resources")
    if os.path.exists(resources_data_dir):
        if os.path.exists(resources_dst):
            shutil.rmtree(resources_dst)  # 如果目标文件夹已存在,先删除
        shutil.copytree(resources_data_dir, resources_dst)

        # 处理resources中的非代码数据（描述统一置空）
        image_files = []
        other_files = []

        for filename in os.listdir(resources_data_dir):
            file_path = os.path.join(resources_data_dir, filename)
            if os.path.isfile(file_path):
                file_ext = os.path.splitext(filename)[1].lower()

                # 跳过代码文件
                if file_ext in CODE_EXTENSIONS:
                    continue

                # 分类图片文件和其他文件
                if file_ext in IMAGE_EXTENSIONS:
                    image_files.append((file_path, filename))
                else:
                    other_files.append(filename)

        # 图片资源描述置空
        for _, filename in image_files:
            info["resources"].append(
                {
                    "type": "image",
                    "path": f"resources/{filename}",
                    "description": "",
                }
            )

        # 处理其他非代码文件
        for filename in other_files:
            info["resources"].append(
                {
                    "type": "other",
                    "path": f"resources/{filename}",
                    "description": "",
                }
            )

    # ========== 保存多页：folder 目录下所有 html 文件 ==========
    html_files = [
        fn for fn in os.listdir(webpage_folder)
        if os.path.isfile(os.path.join(webpage_folder, fn)) and fn.lower().endswith(".html")
    ]
    html_files = sorted(html_files)

    if not html_files:
        raise FileNotFoundError(f"No .html files found in {webpage_folder}")

    for html_name in html_files:
        src_html_path = os.path.join(webpage_folder, html_name)
        with open(src_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        info["dst_code"].append(
            {
                "path": html_name,   # 保持在 dst 根目录
                "code": html_content,
            }
        )

        dst_html_path = os.path.join(dst_repo_dir, html_name)
        with open(dst_html_path, "w", encoding="utf-8") as dst_f:
            dst_f.write(html_content)

        dstcode_count += 1

    for filename in os.listdir(resources_data_dir):
        file_path = os.path.join(webpage_folder, "resources", filename)
        file_ext = os.path.splitext(filename)[1].lower()

        # 只要是定义的代码种类就记录
        if file_ext in CODE_EXTENSIONS:
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()
                info["dst_code"].append(
                    {
                        "path": f"resources/{filename}",
                        
                        "code": code_content,
                    }
                )
                dstcode_count += 1

    # 无截图，描述置空
    info["description"] = ""

    # 写入输出文件
    info_file = os.path.join(output_folder, "info.json")
    with open(info_file, "w", encoding="utf-8") as out_f:
        json.dump(info, out_f, ensure_ascii=False, indent=4)

    print(f"Successfully generated description and saved to {info_file}")


if __name__ == "__main__":
    config = OmegaConf.load("config/api.yaml")
    client = OpenAI(
        base_url=config.api.base_url,
        api_key=config.api.api_key,
    )

    dataset_base_path = "/root/bayes-tmp/data/filter_mp_50"  # 数据集文件夹路径

    # 直接读取dataset_base_path下的所有文件夹
    for web_name in sorted(os.listdir(dataset_base_path)):
        web_path = os.path.join(dataset_base_path, web_name)
        if not os.path.isdir(web_path):
            continue
        output_folder = f"/root/bayes-tmp/data/data_filtered_v3_mp/generation/{web_name}"
        transform_generation(
            client, dataset_base_path, web_name, output_folder
        )
