import argparse
import os
import json
import time
import base64
import requests
import logging
import multiprocessing
import random
import traceback
import itertools
from functools import partial
from tqdm import tqdm
from transformers import AutoTokenizer
from pathlib import Path
from extract_ans import extract_mllm_overall
from prompts.prompt_mllm_check import get_prompt_mllm_checklist
from utils import *

# Parse command line arguments.

system_content = (
    "You are an AI language model engineered to solve user problems through "
    "first-principles thinking and evidence-based reasoning.\n"
    "Your objective is to take reasonable steps, to explain what you are doing "
    "in a way that humans can follow along with, to discover when you get stuck "
    "in a dead-end and try something new, and to discover correct final answers."
)

def get_args() -> argparse.Namespace:
    """
    Parses command-line arguments to obtain input file, output file path,
    number of screenshots to capture, model configuration, and parallel processing options.

    Returns:
    - argparse.Namespace: The parsed arguments from the command line.
    """
    parser = argparse.ArgumentParser(
        description="This program processes data and generates screenshots."
    )

    # Command-line arguments
    parser.add_argument("input_file", help="Path to the input JSON file.")
    parser.add_argument("save_path", help="Path to save the processed output JSON.")
    parser.add_argument("screenshots_dir", help="Directory to store the screenshots.")
    parser.add_argument("count", type=int, help="Number of screenshots to capture.")
    parser.add_argument("model_marker", help="Model marker for identifying the model.")
    parser.add_argument("tokenizer_dir", help="Directory for the tokenizer.")
    parser.add_argument("ip_file_path", help="Directory for the ip list.")
    parser.add_argument(
        "--num_processes",
        type=int,
        default=4,
        help="Number of parallel processes to use (default is 4).",
    )
    return parser.parse_args()


# Initialize global variables and directories
def init_directories(screenshots_dir, save_path):
    """
    Initializes necessary directories for saving screenshots and processed output.

    Parameters:
    - screenshots_dir: Directory to store the screenshots.
    - save_path: Path to store the processed JSON output.

    Returns:
    - screenshots_dir: The directory for saving screenshots.
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    os.makedirs(screenshots_dir, exist_ok=True)
    print(f"Saving screenshots to: {screenshots_dir}")
    return screenshots_dir


# Function to read IPs from the file
def read_ips_from_file(ip_file_path):
    """
    Reads a list of IP addresses from a given file.

    Parameters:
    - ip_file_path: Path to the file containing the list of IPs.

    Returns:
    - ips: List of IP addresses read from the file.
    """
    with open(ip_file_path, "r") as f:
        ips = [line.strip() for line in f.readlines() if line.strip()]
    return ips


# Function to check IP reachability
def check_ip_reachability(ip):
    """
    Checks the reachability of an IP address by sending an HTTP request.

    Parameters:
    - ip: IP address to check.

    Returns:
    - bool: True if the IP is reachable (responds with status 200), False otherwise.
    """
    try:
        response = requests.get(f"http://{ip}:8088/health", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


# Function to validate and filter reachable IPs
def validate_ips(ip_file_path):
    """
    Validates the IPs by checking their reachability and returns only the reachable ones.

    Parameters:
    - ip_file_path: Path to the file containing IPs to validate.

    Returns:
    - reachable_ips: List of reachable IPs.
    """
    if os.path.exists(ip_file_path):
        ip_list = read_ips_from_file(ip_file_path)
    else:
        ip_list = [ip_file_path]
    reachable_ips = [ip for ip in ip_list if check_ip_reachability(ip)]
    return reachable_ips


# Function to initialize IP pool
def init_worker(ip_file_path=None):
    """
    Initializes the worker for parallel processing by setting up an IP pool.

    Parameters:
    - ip_file_path: Path to the file containing IP addresses to initialize the pool.
    """
    global ip_cycle
    if ip_file_path:
        ip_list = validate_ips(ip_file_path)  # Validate IPs once
    else:
        ip_list = []  # Empty list if no file is provided

    print(f"IP pool initialized with {len(ip_list)} reachable IPs: {ip_list}")
    ip_cycle = itertools.cycle(ip_list)


# Function to get next IP from the pool
def get_next_ip():
    """
    Fetches the next IP address from the IP pool in a round-robin manner.

    Returns:
    - str: The next available IP address or None if the IP pool is not initialized.
    """
    try:
        return next(ip_cycle)
    except NameError:
        print("IP pool is not initialized. Please provide valid IP file.")
        return None


# Make request to the model API
def make_request(url, headers, data, max_retries=3):
    """
    Sends a POST request to the model API with retry logic in case of failure.

    Parameters:
    - url: The URL of the API to send the request to.
    - headers: The headers for the request.
    - data: The data to send in the request body.
    - max_retries: Maximum number of retry attempts in case of failure.

    Returns:
    - str: The response content from the model API.
    """
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=data)
            ans = response.json()
            return ans["choices"][0]["message"]["content"].strip()
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"Retried {max_retries} times, all failed")
                print("Last error:", e)
                return ""
            print(f"Attempt {attempt + 1} failed, waiting to retry...")
            print("Error:", e)
            time.sleep(5)


# Make the API request to the model.
def make_api_request(url, headers, data, index, line_data):
    """
    Sends the API request to the model and processes the response.

    Parameters:
    - url: The URL of the model API.
    - headers: The request headers.
    - data: The request data.
    - index: Index of the current item.
    - line_data: Data for the current item.

    Returns:
    - dict: Updated line data with the model response.
    """
    try:
        for i in range(4):  # Try the request up to 4 times
            output_text = make_request(url, headers, data)
            line_data["qvl_reason"] = output_text
            mllm_ans = extract_mllm_overall(index, output_text)
            line_data["qvl_ans"] = mllm_ans
            if line_data["qvl_ans"] is not None:
                return line_data
        return line_data
    except Exception as e:
        print(f"{index} request failed: {e}")
        return line_data


# Add images to the request data.
def add_images_to_data(img_path, data):
    """
    Adds images to the request data by encoding the images to base64 format.

    Parameters:
    - img_path: List of paths to the image files to be included.
    - data: The original data to which the images will be appended.

    Returns:
    - dict: The modified data with the images added.
    """
    try:
        for i in range(len(img_path)):
            with open(img_path[i], "rb") as image_file:
                encoded_image = base64.b64encode(image_file.read()).decode("utf-8")
                new_image = {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded_image}"},
                }
                data["messages"][1]["content"].append(new_image)
        return data
    except Exception as e:
        print(f"Could not add image to data: {e}")
        return data


# Function to process each item
def process_item(
    item_data, tokenizer, count, model, screenshots_dir, ip_file_path=None
):
    """
    Processes each item by handling the request, image processing, and API interaction.

    Parameters:
    - item_data: The data for the current item.
    - tokenizer: The tokenizer used for processing the content.
    - count: The number of screenshots to capture.
    - model: The model marker used for identification.
    - screenshots_dir: Directory for storing screenshots.
    - ip_file_path: Path to the file with the list of IPs.

    Returns:
    - tuple: A tuple containing the index and the updated line data for the item.
    """
    try:
        ip = get_next_ip()
        # Use the random IP in the request URL
        url = f"http://{ip}:8088/v1/chat/completions"

        _, line_data = item_data
        index = line_data["index"]

        headers = {"Content-Type": "application/json"}
        data = {
            "model": f"{model}",
            "messages": [
                {
                    "role": "system",
                    "content": system_content,
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": ""}],
                },
            ],
            "temperature": 0.7,
        }

        # Extract and process the information from the line_data
        img_path, query, answer = extract_information(
            index, line_data, count, screenshots_dir
        )
        checklist = line_data.get("checklist")
        data["messages"][1]["content"][0]["text"] = get_prompt_mllm_checklist(
            checklist, query, answer
        )

        # Process token length
        data["messages"][1]["content"][0]["text"] = truncate_content(
            data["messages"][1]["content"][0]["text"], tokenizer
        )

        # Add images to the request
        data = add_images_to_data(img_path, data)

        # Make the API request
        line_data = make_api_request(url, headers, data, index, line_data)

        return index, line_data

    except Exception as e:
        _, line_data = item_data
        index = line_data["index"]
        print(f"Error in process_item (index={index}): {e}")
        traceback.print_exc()
        return index, line_data


# Main function
def main():
    """
    The main function that orchestrates the entire processing flow, including
    parsing command-line arguments, initializing directories, processing the data,
    and saving the output.
    """
    args = get_args()  # Get arguments from the command line
    start_time = time.time()

    # Initialize directories
    screenshots_dir = init_directories(args.screenshots_dir, args.save_path)

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        args.tokenizer_dir, trust_remote_code=True
    )

    # Initialize IP handling
    init_worker(ip_file_path=args.ip_file_path)

    # Load data from the provided path
    all_data = load_data_from_file(args.input_file)

    total_items = len(all_data)
    print(f"Total {total_items} items to process")

    items_to_process = [(i, item) for i, item in enumerate(all_data)]
    process_func = partial(
        process_item,
        tokenizer=tokenizer,
        count=args.count,
        model=args.model_marker,
        screenshots_dir=screenshots_dir,
        ip_file_path=args.ip_file_path,
    )

    num_processes = args.num_processes
    print(f"Using {num_processes} processes for parallel processing")

    # Process items in parallel
    results = []
    with multiprocessing.Pool(processes=num_processes) as pool:
        for result in tqdm(
            pool.imap_unordered(process_func, items_to_process),
            total=total_items,
            desc="Processing Progress",
        ):
            results.append(result)
            index, item = result
            with open(args.save_path, "a", encoding="utf-8") as w:
                w.write(json.dumps(item, ensure_ascii=False) + "\n")

    # Sort results by index
    results.sort(key=lambda x: x[0])
    processed_data = [item for _, item in results]

    # Save processed data to the output file
    with open(args.save_path, "w", encoding="utf-8") as w:
        for item in processed_data:
            w.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Processing completed, total time: {time.time() - start_time: .2f} seconds")

    # Calculate average scores and lengths
    avg_mllm_score = 0
    error_count = 0
    avg_len = 0
    answer_count = 0
    for data in processed_data:
        try:
            avg_mllm_score += float(data['qvl_ans'])
            answer_str = get_answer(data)
            if 'model_infer_think' in data:
                answer_str = data['model_infer_think'] + answer_str
            avg_len += len(answer_str)
            answer_count += 1
        except:
            error_count += 1
    print(f"Average MLLM score: {avg_mllm_score/answer_count:.4f}")
    print(f"Average answer length: {avg_len/answer_count:.2f}")
    print(f"Error count: {error_count}")


if __name__ == "__main__":
    main()
