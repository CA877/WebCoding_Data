import json
import re


def find_pattern_matches(patterns, data):
    """
    Attempts to find matches for a list of patterns in the provided data.

    Parameters:
    - patterns: A list of regex patterns to try.
    - data: The data to search through.

    Returns:
    - The last matched score (string), or None if no match is found.

    This function iterates through the list of patterns and attempts to match each one with the provided data.
    If any matches are found, the last match is returned. The match should contain the score, 
      which is returned as a string.
    """
    for pattern in patterns:
        matches = re.findall(pattern, data)  # Find all matches of the pattern
        if matches:
            # Return the last matched score (if any matches are found)
            return matches[-1][1]
    return None  # If no match is found, return None


def extract_mllm_overall(line_num, data):
    """
    Extracts the overall score from the given data using predefined patterns.

    Parameters:
    - line_num: The line number for error reporting (used for logging).
    - data: The data from which the score needs to be extracted.

    Returns:
    - The overall score (string) or None if not found.

    This function uses two regex patterns to search for the overall score, first checking for
      the English pattern and then the Chinese pattern.
    If no match is found, it logs an error with the line number.
    """
    patterns = [
        # English pattern for overall score
        r'"Overall Score":\s*(")?(\d+(\.\d+)?|\d+-\d+)(")?',
        # Chinese pattern for overall score
        r'"总体打分":\s*(")?(\d+(\.\d+)?|\d+-\d+)(")?',
    ]

    try:
        overall_score = find_pattern_matches(
            patterns, data)  # Call the function to find a match

        if overall_score:
            return overall_score  # Return the overall score if found

        # Log error if score is not found
        print(
            f"Line {line_num} - 'Overall Score' or 'total_score' field not found")
        return None

    except Exception as e:
        # Log error if an exception occurs during the process
        print(f"Line {line_num} - Parsing error: {e}")
        return None


def extract_last_match(pattern, text):
    """
    Helper function to extract the last match of a given pattern from the text.

    Parameters:
    - pattern: The regular expression pattern to search for.
    - text: The text in which to search for the pattern.

    Returns:
    - The last matched string, or None if no match is found.
    """
    matches = re.findall(
        pattern,
        text,
        re.DOTALL)  # Find all matches of the pattern
    if matches:
        return matches[-1]  # Return the last match if any matches are found
    return None  # If no match is found, return None


def extract_last_html_or_svg_block(text):
    """
    Extracts the last matched HTML or SVG block from the given text.

    Parameters:
    - text: The text in which HTML or SVG blocks need to be extracted.

    Returns:
    - A dictionary containing the type ("html" or "svg") and content of the last matched block.

    This function searches for the last `<html>` and `<svg>` blocks in the provided text and returns
      the last matched one.
    If no match is found, it returns a default value indicating no match was found.
    """
    try:
        html_block = extract_last_match(
            r"(<html[^>]*>.*?</html>)",
            text)  # Try to find the last <html> block
        svg_block = extract_last_match(
            r"(<svg[^>]*>.*?</svg>)",
            text)  # Try to find the last <svg> block

        if html_block:
            # If <html> block is found, return it
            return {"type": "html", "content": html_block}
        elif svg_block:
            # If <svg> block is found, return it
            return {"type": "svg", "content": svg_block}

        # If no <html> or <svg> blocks are found, return default value
        return {"type": "None", "content": "None"}

    except Exception as e:
        # Log any exceptions that occur during the extraction
        print(f"Parsing error: {e}")
        # Return default value in case of error
        return {"type": "None", "content": "None"}


def main():
    """
    The main function to test the functionality of the extract_mllm_overall and extract_last_html_or_svg
    _block functions.

    It demonstrates how to extract overall scores and HTML/SVG content from sample data.
    """
    # Test extract_mllm_overall function with example data
    sample_data_1 = '{"Overall Score": "85.5"}'  # Example with English field
    sample_data_2 = '{"总体打分": "92"}'  # Example with Chinese field
    sample_data_3 = '{"Other Field": "100"}'  # Example with no matching field

    # Test with line numbers for logging
    print("Testing extract_mllm_overall:")
    print(f"Result for sample 1: {extract_mllm_overall(1, sample_data_1)}")
    print(f"Result for sample 2: {extract_mllm_overall(2, sample_data_2)}")
    print(f"Result for sample 3: {extract_mllm_overall(3, sample_data_3)}")

    # Test extract_last_html_or_svg_block function with sample text
    sample_text_1 = """
    <html>
        <head><title>Sample HTML</title></head>
        <body><p>HTML content here</p></body>
    </html>
    <svg><circle cx="50" cy="50" r="40" stroke="green" stroke-width="4" fill="yellow" /></svg>
    """
    sample_text_2 = """
    <svg><rect width="300" height="100" style="fill:rgb(0,0,255);" /></svg>
    """
    sample_text_3 = "No HTML or SVG content here."

    print("\nTesting extract_last_html_or_svg_block:")
    print(
        "Result for sample 1: ", 
            extract_last_html_or_svg_block(sample_text_1))
    print(
        "Result for sample 2: ",
            extract_last_html_or_svg_block(sample_text_2))
    print(
        "Result for sample 3: ",
            extract_last_html_or_svg_block(sample_text_3))


if __name__ == "__main__":
    main()
