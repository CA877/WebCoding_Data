"""Parser-based URL rewriting for online HTML projects."""
from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import tinycss2

from crawl.pipeline_c.main import rewrite_javascript_modules


def absolute_url(value: str, base: str) -> str:
    value = value.strip()
    if not value or value.startswith(('#', 'data:', 'mailto:', 'tel:', 'javascript:')):
        return value
    if value.startswith('blob:'):
        raise ValueError('nonpersistent_blob_resource')
    return urljoin(base, value)


def rewrite_srcset(value: str, base: str) -> str:
    # WHATWG URL collection: commas inside a URL (notably data URLs) are
    # ordinary URL characters; trailing commas separate no-descriptor entries.
    candidates = []
    pos = 0
    while pos < len(value):
        while pos < len(value) and (value[pos].isspace() or value[pos] == ','):
            pos += 1
        start = pos
        while pos < len(value) and not value[pos].isspace():
            pos += 1
        raw = value[start:pos]
        if not raw:
            break
        if raw.endswith(','):
            candidates.append(absolute_url(raw.rstrip(','), base))
            continue
        start = pos
        depth = 0
        while pos < len(value):
            char = value[pos]
            if char == ',' and depth == 0:
                break
            depth += (char == '(') - (char == ')')
            pos += 1
        descriptor = value[start:pos].strip()
        candidates.append(absolute_url(raw, base) + (' ' + descriptor if descriptor else ''))
        pos += 1
    return ', '.join(candidates)


def rewrite_css(value: str, base: str) -> str:
    tokens = tinycss2.parse_component_value_list(value)

    def visit(items):
        import_pending = False
        for token in items:
            if token.type == 'at-keyword':
                import_pending = token.value.lower() == 'import'
            elif import_pending and token.type not in {'whitespace', 'comment'}:
                if token.type == 'string':
                    token.value = absolute_url(token.value, base)
                    token.representation = json.dumps(token.value)
                import_pending = False
            if token.type == 'url':
                token.value = absolute_url(token.value, base)
                token.representation = 'url(' + json.dumps(token.value) + ')'
            elif token.type == 'function':
                if token.lower_name == 'url':
                    args = [x for x in token.arguments if x.type not in {'whitespace', 'comment'}]
                    if len(args) != 1 or args[0].type != 'string':
                        raise ValueError('unparseable_css_url')
                    token.arguments = tinycss2.parse_component_value_list(
                        json.dumps(absolute_url(args[0].value, base)))
                else:
                    # image-set permits quoted URL strings without url().
                    if token.lower_name in {'image-set', '-webkit-image-set'}:
                        for arg in token.arguments:
                            if arg.type == 'string':
                                arg.value = absolute_url(arg.value, base)
                                arg.representation = json.dumps(arg.value)
                    visit(token.arguments)
            elif hasattr(token, 'content'):
                visit(token.content)
            elif token.type == 'error':
                raise ValueError('unparseable_css_resource')
    visit(tokens)
    return tinycss2.serialize(tokens)


def absolutize_html(document: str, final_url: str) -> tuple[str, dict]:
    soup = BeautifulSoup(document, 'html.parser')
    base_node = soup.find('base', href=True)
    base = urljoin(final_url, base_node['href']) if base_node else final_url
    changed = 0
    for node in soup.find_all(True):
        for attr in ('src', 'href', 'poster', 'action', 'formaction', 'xlink:href',
                     'data-src', 'data-lazy-src', 'data-original', 'data-background',
                     'data-bg', 'background'):
            if not node.has_attr(attr):
                continue
            # object[data] below is a URL, arbitrary custom data attributes aren't.
            raw = node[attr]
            new = absolute_url(raw, base)
            if raw != new:
                node[attr] = new
                changed += 1
        if node.name == 'object' and node.get('data'):
            node['data'] = absolute_url(node['data'], base)
        for attr in ('srcset', 'imagesrcset', 'data-srcset', 'data-lazy-srcset'):
            if node.has_attr(attr):
                node[attr] = rewrite_srcset(node[attr], base)
        if node.has_attr('style'):
            node['style'] = rewrite_css(node['style'], base)
        for attr in ('fill', 'stroke', 'filter', 'clip-path', 'mask', 'cursor'):
            if node.has_attr(attr) and 'url(' in node[attr]:
                node[attr] = rewrite_css(node[attr], base)
        if node.name == 'style' and node.string:
            node.string.replace_with(rewrite_css(str(node.string), base))
        if node.name == 'script' and node.string and node.get('type') == 'module':
            node.string.replace_with(rewrite_javascript_modules(str(node.string), base, lambda x: x))
        if node.name == 'script' and node.string and node.get('type') == 'importmap':
            mapping = json.loads(str(node.string))
            for entries in [mapping.get('imports', {}), *mapping.get('scopes', {}).values()]:
                for key, target in list(entries.items()):
                    if isinstance(target, str):
                        entries[key] = absolute_url(target, base)
            if 'scopes' in mapping:
                mapping['scopes'] = {absolute_url(k, base): v for k, v in mapping['scopes'].items()}
            node.string.replace_with(json.dumps(mapping, ensure_ascii=False))
        if node.name == 'iframe' and node.get('srcdoc'):
            node['srcdoc'], _ = absolutize_html(node['srcdoc'], base)
    # A remote base would make fragment-only links leave the saved page.
    for node in soup.find_all('base', href=True):
        del node['href']
    return str(soup), {'document_url': final_url, 'effective_base': base,
                       'rewritten_url_attributes': changed}


def localize_navigation(document: str, mapping: dict[str, str]) -> str:
    soup = BeautifulSoup(document, 'html.parser')
    for node in soup.find_all('a', href=True):
        parts = urlsplit(node['href'])
        target = node['href'].split('#', 1)[0]
        if target in mapping:
            node['href'] = mapping[target] + ('#' + parts.fragment if parts.fragment else '')
    return str(soup)
