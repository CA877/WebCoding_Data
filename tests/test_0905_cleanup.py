from reverse.web_coding_demo.synthetic.supplement_0905 import rejected


def test_length_limit_is_per_output_piece_and_excludes_search():
    assert rejected([{"path": "a.js", "code": "x" * 50000}], True) == []
    assert rejected([{"path": "a.js", "code": "x" * 50001}], True) == ["piece_gt_50k"]
    assert rejected([{"path": "a.js", "search": "x" * 60000, "replace": "y"}]) == []
    assert rejected([{"path": "a.js", "code": "x" * 30000},
                     {"path": "b.js", "code": "y" * 30000}], True) == []


def test_repetition_preserves_exact_lines_and_requires_three_occurrences():
    block = "\n".join(f"line {i}: " + "x" * 30 for i in range(8)) + "\n"
    assert rejected([{"path": "a.html", "code": block * 2}], True) == []
    assert rejected([{"path": "a.html", "code": block * 3}], True) == ["repeated_8line_candidate"]
    assert rejected([{"path": "a.html", "code": "a\n" * 24}], True) == []


def test_duplicate_patch_is_distinct_from_reusing_an_anchor():
    patch = {"path": "a.js", "search": "// footer", "replace": "alert(1);\n// footer"}
    assert rejected([patch, patch]) == ["duplicate_patch"]
    assert rejected([patch, {**patch, "replace": "alert(2);\n// footer"}]) == []


def test_demo_parser_unwraps_cdata_before_exact_replay():
    from reverse.web_coding_demo.synthetic.synthesizer import BaseSynthesizer
    from reverse.web_coding_demo.synthetic.search_replace import apply_search_replace
    raw = '<description><![CDATA[[]]]></description><search_replace path="index.html"><search><![CDATA[<main>]]></search><replace><![CDATA[<main class="ready">]]></replace></search_replace>'
    parsed = BaseSynthesizer.parse_llm_response(None, raw)
    assert BaseSynthesizer.parse_description(None, raw) == []
    output, errors = apply_search_replace([{"path": "index.html", "code": "<main>Hello</main>"}], parsed["modified_files"])
    assert not errors
    assert output[0]["code"] == '<main class="ready">Hello</main>'


def test_script_mode_follows_html_loading_contract():
    from reverse.web_coding_demo.synthetic.supplement_0905 import module_scripts
    code = [{"path": "pages/index.html", "code": '<script src="classic.js"></script><script type="module" src="../app.js?v=1"></script>'}]
    assert module_scripts(code) == {"app.js"}
