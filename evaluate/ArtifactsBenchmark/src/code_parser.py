#!/usr/bin/env python3

import re
import sys


def parse_code(project_value):
    """
    Parses the project value to extract code blocks, classifies them by language,
    and returns a list of dictionaries containing file names, languages, code, and position of each block.
    """
    result = []
    if isinstance(project_value, dict):
        for key, value in project_value.items():
            result.append({"file_name": key, "content": value})
        return result

    all_codes = {}
    css_file_names = []
    js_file_names = []

    matches = re.finditer(r"```(\w+)\n(.*?)```", project_value, flags=re.DOTALL)

    for match in matches:
        begin, end = match.span()
        language = match.group(1).lower()
        code = match.group(2)

        if language == "html":
            result.append(
                {
                    "file_name": "index.html",
                    "language": language,
                    "content": code,
                    "pos": [begin, end],
                }
            )
            css_file_names, js_file_names = extract_css_js_files(code)

        if language not in all_codes:
            all_codes[language] = []
        all_codes[language].append({"code": code, "pos": [begin, end]})

    result.extend(
        process_css_js_files(project_value, all_codes, css_file_names, js_file_names)
    )

    return result


def extract_css_js_files(code):
    """
    Extracts CSS and JS file names from the provided HTML content, excluding any remote file links.
    Returns the extracted CSS and JS file names.
    """
    css_files = re.findall(
        r'<link[^>]*rel=["\'](stylesheet|preload)["\'][^>]*href=["\']((?!https?:\/\/).*?)["\']',
        code,
    )
    js_files = re.findall(r'<script[^>]*src=["\']((?!https?:\/\/).*?)["\']', code)

    css_file_names = [match[1] for match in css_files]
    js_file_names = js_files
    return css_file_names, js_file_names


def process_css_js_files(project_value, all_codes, css_file_names, js_file_names):
    """
    Processes the CSS and JS code blocks in the project value, attaching appropriate file names to the content.
    Also ensures unmatched files are handled.
    """
    result = []
    last_line = ""

    for line in project_value.split("\n"):
        if not re.match(r"```(\w+)", line):
            last_line = line
            continue
        elif re.match(r"```css", line, re.IGNORECASE):
            result.extend(
                process_css_block(last_line, all_codes["css"], css_file_names)
            )
        elif re.match(r"```javascript", line, re.IGNORECASE):
            result.extend(
                process_js_block(last_line, all_codes["javascript"], js_file_names)
            )

    return result


def process_css_block(last_line, css_codes, css_file_names):
    """
    Processes the CSS block and associates it with the appropriate file name,
    either from the provided file names or using a default name.
    """
    result = []
    last_line_match = re.findall(r"([\w\-/]+\.css)", last_line, re.IGNORECASE)
    code_info = css_codes.pop(0)

    if len(css_file_names) == 0:
        result.append(
            {
                "file_name": "styles.css",
                "language": "css",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )
    elif last_line_match:
        result.append(
            {
                "file_name": last_line_match[0],
                "language": "css",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )
        try:
            css_file_names.remove(last_line_match[0])
        except BaseException:
            pass
    else:
        result.append(
            {
                "file_name": css_file_names.pop(0),
                "language": "css",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )

    return result


def process_js_block(last_line, js_codes, js_file_names):
    """
    Processes the JavaScript block and associates it with the appropriate file name,
    either from the provided file names or using a default name.
    """
    result = []
    last_line_match = re.findall(r"([\w\-/]+\.js)", last_line, re.IGNORECASE)
    code_info = js_codes.pop(0)

    if len(js_file_names) == 0:
        result.append(
            {
                "file_name": "script.js",
                "language": "javascript",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )
    elif last_line_match:
        result.append(
            {
                "file_name": last_line_match[0],
                "language": "javascript",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )
        try:
            js_file_names.remove(last_line_match[0])
        except BaseException:
            pass
    else:
        result.append(
            {
                "file_name": js_file_names.pop(0),
                "language": "javascript",
                "content": code_info["code"],
                "pos": code_info["pos"],
            }
        )

    return result


def insert_unmatched_files(html_content, files_to_insert, tag_type, tag_end):
    """
    Inserts unmatched CSS or JS files at the end of the specified HTML tag section (e.g., <head> or <body>).

    Parameters:
    - html_content: The current HTML content.
    - files_to_insert: List of files to insert.
    - tag_type: Type of tag ("css" or "javascript").
    - tag_end: Closing tag to find (e.g., "</head>" or "</body>").

    Returns:
    - The modified HTML content with unmatched files inserted.
    """
    for file in files_to_insert:
        html_content = re.sub(
            tag_end,
            f"<{tag_type}>/* {file} not found in result */</{tag_type}>\n{tag_end}",
            html_content,
            1,
        )
    return html_content


def replace_references_with_code(result):
    """
    Replaces <link> and <script> tags in the HTML content with the corresponding file content.
    If there are unmatched CSS or JS files, they are directly inserted into the HTML.

    Parameters:
    - result: List of file content and file names returned by `parse_code`.

    Returns:
    - The modified HTML content with inline CSS and JS code.
    """
    html_content = next(
        item["content"] for item in result if item["file_name"] == "index.html"
    )

    file_content_map = {
        item["file_name"]: item["content"]
        for item in result
        if item["language"] in ["css", "javascript"]
    }

    css_to_insert = [item["file_name"] for item in result if item["language"] == "css"]
    js_to_insert = [
        item["file_name"] for item in result if item["language"] == "javascript"
    ]

    html_content = re.sub(
        r'<link[^>]*href=["\'](.*?)["\'][^>]*>',
        lambda match: replace_link_tag(match, file_content_map, css_to_insert),
        html_content,
    )
    html_content = re.sub(
        r'<script[^>]*src=["\'](.*?)["\'][^>]*>',
        lambda match: replace_script_tag(match, file_content_map, js_to_insert),
        html_content,
    )

    html_content = insert_unmatched_files(
        html_content, css_to_insert, "style", "</head>"
    )

    html_content = insert_unmatched_files(
        html_content, js_to_insert, "script", "</body>"
    )

    return html_content


def replace_link_tag(match, file_content_map, css_to_insert):
    """
    Replaces the <link> tag's href with the corresponding CSS code if available.

    Parameters:
    - match: The match object of the <link> tag.
    - file_content_map: A dictionary of file names and content.
    - css_to_insert: List of CSS files to insert.

    Returns:
    - The modified <link> tag with inline CSS content if available, otherwise returns the original tag.
    """
    href = match.group(1)
    if href in file_content_map and href.endswith(".css"):
        css_to_insert.remove(href)
        return f"<style>{file_content_map[href]}</style>"
    return match.group(0)


def replace_script_tag(match, file_content_map, js_to_insert):
    """
    Replaces the <script> tag's src with the corresponding JS code if available.

    Parameters:
    - match: The match object of the <script> tag.
    - file_content_map: A dictionary of file names and content.
    - js_to_insert: List of JS files to insert.

    Returns:
    - The modified <script> tag with inline JS content if available, otherwise returns the original tag.
    """
    src = match.group(1)
    if src in file_content_map and src.endswith(".js"):
        js_to_insert.remove(src)
        return f"<script>{file_content_map[src]}</script>"
    return match.group(0)


def extract_html(project_value):
    """
    Extracts HTML content from the provided project value and replaces the references to external CSS and JS files
    with the actual inline code content.

    Parameters:
    - project_value: The project input data containing the HTML and associated code blocks.

    Returns:
    - The final HTML content with embedded CSS and JS.
    """
    all_code = parse_code(project_value)
    html_code = replace_references_with_code(all_code)
    return html_code


def process_file(input_file_path, output_file_path):
    """
    Reads the input file, processes it to generate HTML content, and writes the result to the output file.

    Parameters:
    - input_file_path: The path to the input file containing the project data.
    - output_file_path: The path to the output HTML file to save the result.
    """
    with open(input_file_path, "r", encoding="utf-8") as f:
        project_value = f.read()

    html_code = extract_html(project_value)

    with open(output_file_path, "w", encoding="utf-8") as f:
        f.write(html_code)

    print(f"HTML code has been successfully written to {output_file_path}")


if __name__ == "__main__":
    input_file = "path/to/your/input_file.txt"
    output_file = "path/to/your/output_file.html"
    process_file(input_file, output_file)
