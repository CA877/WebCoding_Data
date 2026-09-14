"""Preserve original code boundaries and explicit model/render-only roles.

Only versioned, explicitly allowlisted public library distributions stay online.
Image-assisted policy may freeze bundles/large files without claiming library identity.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit, urldefrag

from bs4 import BeautifulSoup
import tinycss2

from crawl.pipeline_c.main import rewrite_javascript_modules
from crawl.pipeline_c.qwen_token_gate import count_project_tokens
from .resources import rewrite_css


def external_library(url):
    parts = urlsplit(url)
    if parts.scheme == 'https' and parts.hostname == 'fonts.googleapis.com' and parts.path in {'/css','/css2'}:
        return True
    if parts.scheme != 'https' or parts.query:
        return False
    # A CDN hostname alone is not evidence: restrict both package and artifact.
    patterns = {
        'code.jquery.com': r'/jquery-\d+\.\d+\.\d+(?:\.min)?\.js',
        'cdnjs.cloudflare.com': (
            r'/ajax/libs/(?:jquery/\d+\.\d+\.\d+/jquery(?:\.min)?\.js|'
            r'font-awesome/\d+\.\d+\.\d+/css/(?:all|font-awesome)(?:\.min)?\.css|'
            r'normalize/\d+\.\d+\.\d+/normalize(?:\.min)?\.css)'
        ),
        'cdn.jsdelivr.net': (
            r'/npm/(?:bootstrap@\d+\.\d+\.\d+/dist/(?:css/bootstrap(?:\.min)?\.css|'
            r'js/bootstrap(?:\.bundle)?(?:\.min)?\.js)|'
            r'jquery@\d+\.\d+\.\d+/dist/jquery(?:\.min)?\.js)'
        ),
        'maxcdn.bootstrapcdn.com': r'/bootstrap/\d+\.\d+\.\d+/(?:css/bootstrap(?:\.min)?\.css|js/bootstrap(?:\.min)?\.js)',
    }
    return bool(re.fullmatch(patterns.get(parts.hostname, r'(?!)'), parts.path))


class CodeAssets:
    def __init__(self, project: Path, tokenizer: Path, limit: int, check_access,
                 *, render_only_min_bytes: int = 0):
        self.project, self.tokenizer, self.limit = project, tokenizer, limit
        self.check_access = check_access
        self.files = {}
        self.external = set()
        self.verified_external = {}
        self.request = None
        self.total_bytes = 0
        self.binary_bytes = 0
        self.download_cache = {}
        self.download_cache_bytes = 0
        self.cache_hits = 0
        self.render_only_min_bytes = render_only_min_bytes

    def render_only_reason(self, url, text, byte_count):
        if not self.render_only_min_bytes:
            return None
        if byte_count >= self.render_only_min_bytes:
            return 'large_code_file'
        if re.search(r'(?:^|[./_-])(?:vendors?|bundle|chunks?|webpack|runtime|polyfills?)(?:[./_-]|$)',
                     urlsplit(url).path, re.I):
            return 'bundle_filename'
        if re.search(r'webpackBootstrap|__webpack_require__|webpackJsonp|webpackChunk',text):
            return 'bundle_signature'
        return None

    def write_render_dependencies(self):
        if not self.render_only_min_bytes:
            return
        rows = [dict(x) for x in self.files.values() if x.get('model_input') is False]
        manifest = {'schema':'webcoding_render_dependencies_v1',
            'usage':'image_based_edit_repair_only','large_file_bytes':self.render_only_min_bytes,
            'files':rows,'patch_policy':'excluded_files_are_read_only; never inject defects into them'}
        path = self.project/'render_dependencies.json'
        temporary = path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        temporary.replace(path)

    def fetch(self, url, timeout):
        # Per-site immutable downloads survive candidate rollback. Only source
        # bytes are reused: localization, dependency checks and token gates rerun.
        if url in self.download_cache:
            self.cache_hits += 1
            return self.download_cache[url]
        self.check_access(url)
        response = self.request.get(url,timeout=timeout,max_redirects=0)
        if response.status != 200:
            return response
        body = response.body()
        if len(body) <= 16_000_000:
            while self.download_cache and self.download_cache_bytes + len(body) > 16_000_000:
                key = next(iter(self.download_cache))
                self.download_cache_bytes -= len(self.download_cache.pop(key).body())
            response = SimpleNamespace(status=200,url=getattr(response,'url',url),
                headers=dict(getattr(response,'headers',{})),body=lambda:body)
            self.download_cache[url] = response
            self.download_cache_bytes += len(body)
        return response

    def checkpoint(self):
        return dict(self.files), set(self.external), self.total_bytes, dict(self.verified_external), self.binary_bytes

    def rollback(self, checkpoint):
        previous, external, size, verified, binary_size = checkpoint
        kept = {item['file'] for item in previous.values()}
        for item in self.files.values():
            path = self.project / item['file']
            if item['file'] not in kept and path.exists():
                path.unlink()
        self.files, self.external, self.total_bytes = previous, external, size
        self.verified_external = verified
        self.binary_bytes = binary_size
        self.write_render_dependencies()

    def binary(self, url):
        if url.startswith(('data:','#')):
            return url
        url, fragment = urldefrag(url)
        suffix = '#' + fragment if fragment else ''
        if url in self.files:
            return self.files[url]['file'] + suffix
        response = self.fetch(url,15000)
        if response.status != 200:
            raise ValueError(f'font_resource_http_{response.status}:{url}')
        body = response.body()
        if (len(body) > 8_000_000 or self.binary_bytes + len(body) > 32_000_000
                or len(self.files) >= 200):
            raise ValueError('binary_resource_safety_limit')
        if 'html' in response.headers.get('content-type','').lower():
            raise ValueError('font_resource_is_html:' + url)
        extension = Path(urlsplit(url).path).suffix.lower()
        if extension not in {'.woff','.woff2','.ttf','.otf','.eot','.svg'}:
            extension = '.bin'
        name = 'media/' + hashlib.sha256(url.encode()).hexdigest()[:20] + extension
        path = self.project / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(body)
        self.binary_bytes += len(body)
        self.files[url] = {'url':url,'final_url':response.url,'file':name,'kind':'font',
            'bytes':len(body),'source_sha256':hashlib.sha256(body).hexdigest(),
            'saved_sha256':hashlib.sha256(body).hexdigest()}
        return name + suffix

    def identify_distribution(self, body, kind):
        """Banner gives candidates only; exact bytes prove library identity."""
        prefix = body[:1500].decode('utf-8', errors='replace')
        candidates = []
        jquery = re.search(r'jQuery(?: JavaScript Library)? v(\d+\.\d+\.\d+)', prefix)
        bootstrap = re.search(r'Bootstrap\s+v(\d+\.\d+\.\d+)', prefix)
        if jquery and kind == 'js':
            candidates.extend('https://code.jquery.com/jquery-'+jquery[1]+suffix+'.js'
                              for suffix in ('.min', ''))
        if bootstrap and 'bootswatch' not in prefix.lower():
            artifacts = ('bootstrap', 'bootstrap.bundle') if kind == 'js' else ('bootstrap',)
            candidates.extend(f'https://cdnjs.cloudflare.com/ajax/libs/twitter-bootstrap/{bootstrap[1]}/{kind}/{artifact}{suffix}.{kind}'
                              for artifact in artifacts for suffix in ('.min', ''))
        for candidate in candidates:
            try:
                response = self.fetch(candidate,10000)
                if response.status == 200 and response.body() == body:
                    return candidate
            except Exception:
                # Failed identity checks never justify externalizing unknown code.
                continue
        return None

    def save(self, url, kind):
        url = urldefrag(url)[0]
        if url.startswith('data:'):
            return url
        if url in self.external:
            return url
        if external_library(url):
            self.external.add(url)
            return url
        if url in self.files:
            return self.files[url]['file']
        if len(self.files) >= 100 or self.total_bytes > 8_000_000:
            raise ValueError('code_resource_safety_limit')
        response = self.fetch(url,15000)
        visited = {url}
        for _ in range(6):
            if response.status not in {301,302,303,307,308}:
                break
            target = urljoin(response.url, response.headers.get('location', ''))
            if target in visited:
                raise ValueError('code_resource_redirect_loop')
            visited.add(target)
            response = self.fetch(target,15000)
        if response.status != 200:
            raise ValueError(f'code_resource_http_{response.status}:{url}')
        body = response.body()
        if len(body) > 4_000_000:
            raise ValueError('code_resource_safety_limit')
        mime = response.headers.get('content-type', '').lower()
        if 'text/html' in mime or body.lstrip().lower().startswith((b'<!doctype html', b'<html')):
            raise ValueError('code_resource_is_html:' + url)
        try:
            text = body.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('unsupported_code_encoding:' + url) from exc
        exclusion = (self.render_only_reason(url,text,len(body))
                     or self.render_only_reason(response.url,text,len(body)))
        # Saving a frozen resource needs no speculative public-library identity probes.
        distribution = None if exclusion else self.identify_distribution(body, kind)
        if distribution:
            self.external.add(url)
            self.verified_external[url] = {'url':url, 'distribution_url':distribution,
                'sha256':hashlib.sha256(body).hexdigest(), 'evidence':'exact_distribution_bytes'}
            return url
        name = 'code/' + hashlib.sha256(url.encode()).hexdigest()[:20] + '.' + kind
        path = self.project / name
        path.parent.mkdir(exist_ok=True)
        # Register before descending so module and CSS import cycles terminate.
        self.files[url] = {'url':url, 'final_url':response.url, 'file':name,
            'source_sha256':hashlib.sha256(body).hexdigest(), 'bytes':len(body),
            'model_input':not bool(exclusion),'editable':not bool(exclusion),
            'excluded_from_code_tokens':bool(exclusion),
            'exclusion_reason':exclusion,'role':'render_only' if exclusion else 'editable_code'}
        self.total_bytes += len(body)
        path.write_text(text, encoding='utf-8')
        self.write_render_dependencies()
        if count_project_tokens(self.project, self.tokenizer) > self.limit:
            raise ValueError('saved_code_tokens_over_limit')
        if kind == 'css':
            text = self.css(text, response.url, nested=True)
        else:
            text = rewrite_javascript_modules(text, response.url,
                lambda target: self.relative(self.save(target, 'js'), nested=True))
        path.write_text(text, encoding='utf-8')
        self.files[url]['saved_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.write_render_dependencies()
        return name

    @staticmethod
    def relative(value, nested=False):
        if value.startswith('code/'):
            return './' + value.removeprefix('code/') if nested else './' + value
        if value.startswith('media/'):
            return '../' + value if nested else './' + value
        return value

    def css(self, text, base, nested=False):
        rules = tinycss2.parse_stylesheet(rewrite_css(text, base))
        # Component-token parsing can succeed while stylesheet grammar fails
        # (for example a trailing declaration without a rule block). Preserve
        # the source and reject the candidate instead of serializing ParseError.
        for rule in rules:
            if rule.type == 'error':
                raise ValueError(f'unparseable_css_stylesheet:{rule.source_line}:{rule.source_column}')
        def localize_fonts(tokens):
            for token in tokens:
                if token.type == 'url':
                    token.value = self.relative(self.binary(token.value), nested)
                    token.representation = 'url(' + json.dumps(token.value) + ')'
                elif token.type == 'function':
                    if token.lower_name == 'url':
                        raw = next(x.value for x in token.arguments if x.type == 'string')
                        token.arguments = tinycss2.parse_component_value_list(
                            json.dumps(self.relative(self.binary(raw), nested)))
                    else:
                        localize_fonts(token.arguments)
        for rule in rules:
            if rule.type == 'at-rule' and rule.lower_at_keyword == 'font-face' and rule.content:
                localize_fonts(rule.content)
            if rule.type != 'at-rule' or rule.lower_at_keyword != 'import':
                continue
            tokens = [x for x in rule.prelude if x.type not in {'whitespace','comment'}]
            if not tokens:
                raise ValueError('empty_css_import')
            token = tokens[0]
            if token.type in {'string','url'}:
                target = token.value
            elif token.type == 'function' and token.lower_name == 'url':
                target = next(x.value for x in token.arguments if x.type == 'string')
            else:
                raise ValueError('unsupported_css_import')
            local = self.relative(self.save(target, 'css'), nested)
            replacement = tinycss2.parse_component_value_list(json.dumps(local))[0]
            rule.prelude[rule.prelude.index(token)] = replacement
        return tinycss2.serialize(rules)

    def html(self, text, base, request):
        self.request = request
        soup = BeautifulSoup(text, 'html.parser')
        if any(node.find_parent('noscript') is None for node in soup.find_all(['iframe','frame'])):
            # Embedded documents need their own code/resource capture; don't hide them outside 40K.
            raise ValueError('unsupported_embedded_document')
        for node in soup.find_all(['script','link','style']):
            # Chromium runs with scripting enabled: noscript markup is inert
            # text, even though html.parser represents it as descendant tags.
            if node.find_parent('noscript') is not None:
                continue
            attr, kind = None, None
            if node.name == 'script' and node.get('src'):
                attr, kind = 'src', 'js'
            elif node.name == 'link' and node.get('href'):
                rel = set(node.get('rel', []))
                if 'stylesheet' in rel or node.get('as') == 'style':
                    attr, kind = 'href', 'css'
                elif 'modulepreload' in rel or node.get('as') == 'script':
                    attr, kind = 'href', 'js'
                elif node.get('as') == 'font':
                    attr, kind = 'href', 'font'
            if attr:
                local = self.binary(urljoin(base, node[attr])) if kind == 'font' else self.save(urljoin(base, node[attr]), kind)
                node[attr] = self.relative(local)
                if local.startswith(('code/','media/')) and node.has_attr('integrity'):
                    digest = hashlib.sha384((self.project/local).read_bytes()).digest()
                    node['integrity'] = 'sha384-' + base64.b64encode(digest).decode()
            if node.name == 'style' and node.string:
                node.string.replace_with(self.css(str(node.string), base))
            if node.name == 'script' and node.string and node.get('type') == 'module':
                node.string.replace_with(rewrite_javascript_modules(str(node.string), base,
                    lambda target:self.relative(self.save(target, 'js'))))
            if node.name == 'script' and node.string and node.get('type') == 'importmap':
                mapping = json.loads(str(node.string))
                for entries in [mapping.get('imports',{}), *mapping.get('scopes',{}).values()]:
                    for key, target in entries.items():
                        if isinstance(target, str):
                            if target.endswith('/'):
                                raise ValueError('unsupported_importmap_prefix')
                            entries[key] = self.relative(self.save(urljoin(base,target), 'js'))
                if mapping.get('scopes'):
                    raise ValueError('unsupported_importmap_scopes')
                node.string.replace_with(json.dumps(mapping))
        return str(soup)

    def manifest(self):
        return {'saved':list(self.files.values()),
                'download_cache_hits':self.cache_hits,
                'external_libraries':[dict(self.verified_external.get(x, {'url':x,'evidence':
                    'font_stylesheet_provider_endpoint' if urlsplit(x).hostname == 'fonts.googleapis.com'
                    else 'versioned_library_distribution_allowlist'}),
                    model_input=False,editable=False,excluded_from_code_tokens=True)
                                      for x in sorted(self.external)]}
