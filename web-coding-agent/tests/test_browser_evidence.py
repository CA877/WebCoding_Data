from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web

from src.orchestration.browser_evidence import (
    _action_settle_ms,
    _is_invalid_test_contract_error,
    _matches,
    _same_origin_route_url,
    collect_browser_evidence,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_nonempty_match_rejects_missing_and_blank_runtime_values():
    assert _matches("artifact-7", "", "nonempty") is True
    assert _matches(None, "", "nonempty") is False
    assert _matches("  ", "", "nonempty") is False


def test_evaluate_syntax_error_is_invalid_test_contract():
    error = RuntimeError("Page.evaluate: SyntaxError: Illegal return statement")

    assert _is_invalid_test_contract_error("evaluate", error) is True
    assert _is_invalid_test_contract_error("click", error) is False


def test_action_settle_ms_is_explicit_and_bounded():
    assert _action_settle_ms({"action": "fill", "settle_ms": 200}, "fill") == 200
    assert _action_settle_ms({"action": "fill"}, "fill") == 0
    assert _action_settle_ms({"action": "evaluate", "settle_ms": 250}, "evaluate") == 0


def test_same_origin_route_url_accepts_only_bounded_hash_router_paths():
    assert (
        _same_origin_route_url("http://127.0.0.1:3000/preview", "/#/catalog")
        == "http://127.0.0.1:3000/#/catalog"
    )
    with pytest.raises(ValueError, match="unsafe browser route"):
        _same_origin_route_url("http://127.0.0.1:3000/preview", "/#https://evil.test")


@pytest.mark.anyio
async def test_console_gate_ignores_implicit_favicon_but_keeps_real_resource_url(
    tmp_path: Path,
):
    async def page(_request):
        return web.Response(
            text='<main>Ready</main><script src="/missing.js"></script>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "RESOURCE-CLOSURE",
                    "route": "/",
                    "actions": [{"action": "assert_no_console_errors"}],
                }
            ],
            output_path=tmp_path / "resource-errors.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    step = result["checks"][0]["steps"][0]
    assert step["ok"] is False
    assert any("missing.js" in item for item in step["output"]["actual"])
    assert all("favicon.ico" not in item for item in step["output"]["actual"])


@pytest.mark.anyio
async def test_browser_evidence_preserves_same_route_state_across_split_parts(
    tmp_path: Path,
):
    async def root(_request):
        return web.Response(text="<main id='home'>Home</main>", content_type="text/html")

    async def catalog(_request):
        return web.Response(
            text="""
            <main><input id='query'><output id='value'></output>
            <script>
              document.querySelector('#query').addEventListener('input', event => {
                document.querySelector('#value').textContent = event.target.value;
              });
            </script></main>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/catalog.html", catalog)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    output = tmp_path / "browser.json"
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "UI-FLOW__part1",
                    "route": "/catalog.html",
                    "actions": [
                        {"action": "fill", "selector": "#query", "value": "atlas"},
                        {"action": "evaluate", "expression": "document.querySelector('#value').textContent === 'atlas'"},
                    ],
                },
                {
                    "id": "UI-FLOW__part1__part2",
                    "route": "/catalog.html",
                    "actions": [
                        {"action": "evaluate", "expression": "document.querySelector('#query').value === 'atlas'"},
                    ],
                },
            ],
            output_path=output,
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok"]
    assert all(item["route"] == "/catalog.html" for item in result["checks"])
    assert result["checks"][0]["url"].endswith("/catalog.html")


@pytest.mark.anyio
async def test_browser_evidence_isolates_storage_between_top_level_checks(tmp_path: Path):
    async def root(_request):
        return web.Response(text="<main>Ready</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "WRITE",
                    "route": "/",
                    "actions": [
                        {"action": "set_storage_value", "storage": "local", "key": "state", "value": "atlas"},
                        {"action": "assert_storage_value", "storage": "local", "key": "state", "value": "atlas"},
                    ],
                },
                {
                    "id": "ISOLATED",
                    "route": "/",
                    "actions": [
                        {"action": "assert_storage_value", "storage": "local", "key": "state", "value": None},
                    ],
                },
            ],
            output_path=tmp_path / "isolated.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok"]


@pytest.mark.anyio
async def test_browser_evidence_compares_attribute_snapshot_after_reload(tmp_path: Path):
    async def root(_request):
        return web.Response(
            text="<article id='card' data-id='artifact-1'>Artifact</article>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "ATTRIBUTE-SNAPSHOT",
                    "route": "/",
                    "actions": [
                        {
                            "action": "capture_attribute",
                            "selector": "#card",
                            "name": "data-id",
                            "snapshot": "first-card-id",
                        },
                        {"action": "reload"},
                        {
                            "action": "assert_attribute",
                            "selector": "#card",
                            "name": "data-id",
                            "snapshot": "first-card-id",
                        },
                    ],
                }
            ],
            output_path=tmp_path / "attribute-snapshot.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"
    assert result["checks"][0]["steps"][-1]["output"] == {
        "actual": "artifact-1",
        "expected": "artifact-1",
    }


@pytest.mark.anyio
async def test_browser_evidence_returns_to_declared_route_after_check_navigates_away(
    tmp_path: Path,
):
    async def root(_request):
        return web.Response(
            text="<main id='root'>Root <a id='go' href='/other'>Other</a></main>",
            content_type="text/html",
        )

    async def other(_request):
        return web.Response(text="<main id='other'>Other</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", root)
    app.router.add_get("/other", other)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "NAVIGATE",
                    "route": "/",
                    "actions": [
                        {"action": "click", "selector": "#go"},
                        {"action": "assert_url", "value": "/other"},
                    ],
                },
                {
                    "id": "ROOT-AGAIN",
                    "route": "/",
                    "actions": [{"action": "assert_visible", "selector": "#root"}],
                },
            ],
            output_path=tmp_path / "route-reset.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok"]


@pytest.mark.anyio
async def test_assert_text_waits_for_delayed_ui_value(tmp_path: Path):
    async def root(_request):
        return web.Response(
            text=(
                "<button id='increment'>Increment</button><span id='total'>0</span>"
                "<script>document.querySelector('#increment').onclick=()=>"
                "setTimeout(()=>document.querySelector('#total').textContent='1',250)</script>"
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{
                "id": "DELAYED-TEXT",
                "route": "/",
                "actions": [
                    {"action": "click", "selector": "#increment"},
                    {
                        "action": "assert_text",
                        "selector": "#total",
                        "value": "1",
                        "match": "exact",
                    },
                ],
            }],
            output_path=tmp_path / "delayed-text.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"


@pytest.mark.anyio
async def test_browser_evidence_resets_hash_drift_on_the_same_path(tmp_path: Path):
    async def root(_request):
        return web.Response(
            text="""
            <main id="home">Home <a id="go" href="#/library">Library</a></main>
            <script>
              addEventListener('hashchange', () => {
                document.querySelector('main').id = location.hash ? 'library' : 'home';
              });
            </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "HASH-NAVIGATE",
                    "route": "/",
                        "actions": [
                            {"action": "click", "selector": "#go"},
                            {
                                "action": "evaluate",
                                "expression": "location.hash === '#/library'",
                            },
                        ],
                },
                {
                    "id": "ROOT-AGAIN",
                    "route": "/",
                    "actions": [{"action": "assert_visible", "selector": "#home"}],
                },
            ],
            output_path=tmp_path / "hash-route-reset.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok"]
    assert result["checks"][1]["url"].endswith("/")


@pytest.mark.anyio
async def test_browser_evidence_preserves_hash_across_split_check_parts(tmp_path: Path):
    async def root(_request):
        return web.Response(
            text="""
            <button id="set">Set</button><output id="value">All</output>
            <script>
              set.onclick = () => { location.hash = 'gallery?type=Timepiece'; };
              function render() {
                value.textContent = location.hash.includes('Timepiece') ? 'Timepiece' : 'All';
              }
              addEventListener('hashchange', render); render();
            </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "FILTER__part1",
                    "route": "/",
                    "actions": [
                        {"action": "click", "selector": "#set"},
                        {"action": "assert_hash", "value": "Timepiece", "match": "contains"},
                        {"action": "reload"},
                    ],
                },
                {
                    "id": "FILTER__part2",
                    "route": "/",
                    "actions": [
                        {"action": "assert_text", "selector": "#value", "value": "Timepiece"}
                    ],
                },
            ],
            output_path=tmp_path / "split-hash-state.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok"]
    assert "Timepiece" in result["checks"][1]["url"]


@pytest.mark.anyio
async def test_browser_evidence_executes_typed_dom_aria_and_console_assertions(
    tmp_path: Path,
):
    async def page(_request):
        return web.Response(
            text="""
            <label id="query-label" for="query">Search</label>
            <input id="query" aria-labelledby="query-label" required>
            <button id="toggle" aria-expanded="false">Open</button>
            <section id="panel" hidden>Details</section>
            <script>
              toggle.addEventListener('click', () => {
                toggle.setAttribute('aria-expanded', 'true');
                panel.hidden = false;
                localStorage.setItem('panel', JSON.stringify({state: 'open'}));
              });
            </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "UI-ARIA",
                    "route": "/",
                    "actions": [
                        {"action": "click", "selector": "#toggle"},
                        {
                            "action": "assert_aria",
                            "selector": "#toggle",
                            "attribute": "aria-expanded",
                            "value": True,
                        },
                    ],
                },
                    {
                        "id": "UI-STORAGE",
                        "route": "/",
                        "actions": [
                            {"action": "click", "selector": "#toggle"},
                            {
                                "action": "assert_storage_value",
                            "storage": "local",
                            "key": "panel",
                            "value": "open",
                            "match": "contains",
                        }
                    ],
                },
                {
                    "id": "UI-CONSOLE",
                    "route": "/",
                    "actions": [{"action": "assert_no_console_errors"}],
                },
                {
                    "id": "UI-AX-STATE",
                    "route": "/",
                    "actions": [
                        {
                            "action": "assert_aria",
                            "selector": "#query",
                            "attribute": "role",
                            "value": "textbox",
                        },
                        {
                            "action": "assert_aria",
                            "selector": "#query",
                            "attribute": "accessible_name",
                            "value": "Search",
                        },
                        {
                            "action": "assert_property",
                            "selector": "#query",
                            "name": "required",
                            "value": True,
                        },
                    ],
                },
            ],
            output_path=tmp_path / "typed.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok", "ok", "ok", "ok"]
    assert result["checks"][0]["steps"][-1]["output"] == {
        "actual": "true",
        "expected": True,
    }
    assert result["checks"][-1]["evidence_route"] == [
        "real_browser", "ax_semantics", "internal_state", "dom"
    ]


@pytest.mark.anyio
async def test_browser_evidence_executes_hash_storage_fixture_and_computed_style(
    tmp_path: Path,
):
    async def page(_request):
        return web.Response(
            text="""
            <style>#panel { display: none; }</style>
            <a id="report-link" href="#/report">Report</a>
            <section id="panel">Report panel</section>
            <output id="stored"></output>
            <script>
              function render() {
                if (location.hash === '#/report') panel.style.display = 'block';
                stored.textContent = localStorage.getItem('fixture') || '';
              }
              addEventListener('hashchange', render);
              render();
            </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "HASH-STATE",
                    "route": "/",
                    "actions": [
                        {
                            "action": "set_storage_value",
                            "storage": "local",
                            "key": "fixture",
                            "value": {"page": 2},
                            "encoding": "json",
                        },
                        {"action": "set_hash", "value": "#/report", "settle_ms": 50},
                        {"action": "reload"},
                        {"action": "assert_hash", "value": "#/report"},
                        {
                            "action": "assert_computed_style",
                            "selector": "#panel",
                            "property": "display",
                            "value": "block",
                        },
                        {
                            "action": "assert_text",
                            "selector": "#stored",
                            "value": '"page":2',
                            "match": "contains",
                        },
                    ],
                }
            ],
            output_path=tmp_path / "hash-state-style.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in result["checks"]] == ["ok"]
    assert "rendered_style" in result["checks"][0]["evidence_route"]


@pytest.mark.anyio
async def test_collection_visibility_and_text_assertions_are_not_strict_singletons(
    tmp_path: Path,
):
    async def page(_request):
        return web.Response(
            text=(
                '<article class="card">Timepiece One</article>'
                '<article class="card">Timepiece Two</article>'
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{
                "id": "COLLECTION",
                "route": "/",
                "actions": [
                    {"action": "assert_visible", "selector": ".card"},
                    {
                        "action": "assert_text",
                        "selector": ".card",
                        "value": "Timepiece",
                        "match": "contains",
                    },
                ],
            }],
            output_path=tmp_path / "collection.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"
    assert result["checks"][0]["steps"][0]["output"]["actual"] == [True, True]


@pytest.mark.anyio
async def test_visible_assertion_waits_for_async_target_after_click(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text=(
                '<button id="start">Start</button><div id="target" hidden>Done</div>'
                '<script>start.onclick=()=>setTimeout(()=>target.hidden=false,80)</script>'
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[
                {
                    "id": "ASYNC-TARGET",
                    "route": "/",
                    "actions": [
                        {"action": "click", "selector": "#start"},
                        {"action": "assert_visible", "selector": "#target"},
                    ],
                }
            ],
            output_path=tmp_path / "async-target.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"


@pytest.mark.anyio
async def test_failed_flow_stops_before_cascading_dependent_timeouts(tmp_path: Path):
    async def page(_request):
        return web.Response(text="<main>Ready</main>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "FAIL-FAST", "route": "/", "actions": [
                {"action": "assert_visible", "selector": "#missing"},
                {"action": "click", "selector": "#also-missing"},
            ]}],
            output_path=tmp_path / "fail-fast.json",
            headless=True,
            action_timeout_ms=100,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "action_failed"
    assert len(result["checks"][0]["steps"]) == 1


@pytest.mark.anyio
async def test_visible_failure_records_hidden_ancestor_diagnostic(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text='<section id="gallery" style="display:none"><div id="detail">Ready</div></section>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "HIDDEN-PARENT", "route": "/", "actions": [
                {"action": "assert_visible", "selector": "#detail"},
            ]}],
            output_path=tmp_path / "hidden-parent.json",
            headless=True,
            action_timeout_ms=100,
        )
    finally:
        await runner.cleanup()

    step = result["checks"][0]["steps"][0]
    assert step["visibility_diagnostic"]["matched_count"] == 1
    assert step["visibility_diagnostic"]["hidden_ancestors"][0]["label"] == "#gallery"
    assert "display=none" in step["visibility_diagnostic"]["hidden_ancestors"][0]["hidden_reasons"]


@pytest.mark.anyio
async def test_missing_state_selector_records_existing_base_selector(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text='<a class="sidebar-item" data-name="Audio Studio Driver">Audio</a>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "STATE", "route": "/", "actions": [{
                "action": "assert_visible",
                "selector": 'a.sidebar-item[data-name="Audio Studio Driver"][class~="highlighted"]',
            }]}],
            output_path=tmp_path / "state.json",
            headless=True,
            action_timeout_ms=100,
        )
    finally:
        await runner.cleanup()

    diagnostic = result["checks"][0]["steps"][0]["visibility_diagnostic"]
    assert diagnostic["matched_count"] == 0
    assert diagnostic["base_matched_count"] == 1
    assert diagnostic["base_selector"] == 'a.sidebar-item[data-name="Audio Studio Driver"]'


@pytest.mark.anyio
async def test_hidden_assertion_accepts_css_interaction_hidden_surface(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text=(
                "<style>#menu{transition:opacity .05s}"
                ".closed{opacity:0;pointer-events:none}</style>"
                '<button id="close-menu">Close</button><nav id="menu">Menu</nav>'
                '<script>document.querySelector("#close-menu").onclick=()=>'
                'document.querySelector("#menu").className="closed"</script>'
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "CSS-HIDDEN", "route": "/", "actions": [
                {"action": "click", "selector": "#close-menu"},
                {"action": "assert_hidden", "selector": "#menu"},
            ]}],
            output_path=tmp_path / "css-hidden.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"


@pytest.mark.anyio
async def test_click_time_scroll_snapshot_survives_actionability_scroll(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text="""
              <main style="height:1800px;padding-top:700px">
                <button id="open-detail">Open</button><button id="go-back">Back</button>
              </main>
              <script>
                let saved = 0;
                document.querySelector('#open-detail').addEventListener('click', () => { saved = scrollY; scrollTo(0, 0); });
                document.querySelector('#go-back').addEventListener('click', () => scrollTo(0, saved));
              </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "SCROLL-SNAPSHOT", "route": "/", "actions": [
                {"action": "set_viewport", "width": 800, "height": 400},
                {"action": "scroll", "y": 500},
                {
                    "action": "click",
                    "selector": "#open-detail",
                    "capture_scroll_as": "before-open",
                },
                {"action": "click", "selector": "#go-back"},
                {"action": "assert_scroll", "snapshot": "before-open"},
            ]}],
            output_path=tmp_path / "scroll-snapshot.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    check = result["checks"][0]
    assert check["status"] == "ok"
    assert check["steps"][2]["output"]["scroll_y"] > 0


@pytest.mark.anyio
async def test_in_view_assertion_uses_viewport_geometry(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text='<main style="height:1200px"><div id="target" style="margin-top:700px">Target</div></main>',
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{"id": "IN-VIEW", "route": "/", "actions": [
                {"action": "set_viewport", "width": 800, "height": 400},
                {"action": "scroll", "y": 600},
                {"action": "assert_in_view", "selector": "#target"},
            ]}],
            output_path=tmp_path / "in-view.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"


@pytest.mark.anyio
async def test_runtime_page_error_is_attached_to_failed_check(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text=(
                '<button id="ready">Ready</button>'
                '<script>document.addEventListener("DOMContentLoaded",()=>missingHelper())</script>'
            ),
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{
                "id": "RUNTIME-ERROR",
                "route": "/",
                "actions": [
                    {"action": "assert_visible", "selector": "#ready"},
                ],
            }],
            output_path=tmp_path / "runtime-error.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    check = result["checks"][0]
    assert check["status"] == "action_failed"
    assert any("missingHelper" in error for error in check["console_errors"])


@pytest.mark.anyio
async def test_browser_evidence_executes_0805_advanced_interaction_primitives(
    tmp_path: Path,
):
    async def advanced(_request):
        return web.Response(
            text="""
            <style>
              #source, #target { width: 80px; height: 40px; margin: 8px; border: 1px solid; }
              #ready { display: none; }
              #print-state { display: none; }
              @media print { #print-state { display: block; } }
            </style>
            <button id="tip">Hover</button>
            <button id="menu">Context</button>
            <div id="source" draggable="true">source</div><div id="target">target</div>
            <input id="upload" type="file"><output id="ready">ready</output>
            <div id="print-state">print</div>
            <script>
              const state = document.body.dataset;
              tip.addEventListener('mouseenter', () => state.hovered = 'yes');
              menu.addEventListener('contextmenu', event => {
                event.preventDefault(); state.context = 'yes';
              });
              source.addEventListener('dragstart', event => event.dataTransfer.setData('text/plain', 'source'));
              target.addEventListener('dragover', event => event.preventDefault());
              target.addEventListener('drop', event => {
                event.preventDefault(); state.dropped = event.dataTransfer.getData('text/plain');
              });
              upload.addEventListener('change', async () => {
                state.upload = await upload.files[0].text();
                setTimeout(() => { ready.style.display = 'block'; }, 40);
              });
            </script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", advanced)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{
                "id": "UI-ADVANCED",
                "route": "/",
                "actions": [
                    {"action": "hover", "selector": "#tip"},
                    {"action": "click", "selector": "#menu", "button": "right"},
                    {"action": "drag_and_drop", "source_selector": "#source", "target_selector": "#target"},
                    {
                        "action": "set_input_files",
                        "selector": "#upload",
                        "files": [{"name": "sample.txt", "mime_type": "text/plain", "content": "0805"}],
                    },
                    {"action": "wait_for", "selector": "#ready", "state": "visible", "timeout_ms": 1000},
                    {"action": "emulate_media", "media": "print"},
                    {
                        "action": "evaluate",
                        "expression": "document.body.dataset.hovered === 'yes' && document.body.dataset.context === 'yes' && document.body.dataset.dropped === 'source' && document.body.dataset.upload === '0805' && getComputedStyle(document.querySelector('#print-state')).display === 'block'",
                    },
                ],
            }],
            output_path=tmp_path / "advanced.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert result["checks"][0]["status"] == "ok"
    assert all(step["ok"] for step in result["checks"][0]["steps"])


@pytest.mark.anyio
async def test_new_surface_visual_sanity_catches_nearly_invisible_text(tmp_path: Path):
    async def page(_request):
        return web.Response(
            text="""
            <style>
              body { color: #e6ebf5; background: #0a0e1a; }
              #panel { display: none; background: #f9fafb; }
            </style>
            <button id="show">Show summary</button>
            <section id="panel"><span>0 Downloads</span></section>
            <script>show.onclick = () => panel.style.display = 'block';</script>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        result = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=[{
                "id": "NEW-SUMMARY",
                "route": "/",
                "actions": [
                    {"action": "click", "selector": "#show"},
                    {"action": "assert_visible", "selector": "#panel"},
                ],
            }],
            visual_sanity_selectors=[{
                "route": "/", "selector": "#panel", "min_count": 1, "max_count": 1
            }],
            output_path=tmp_path / "contrast.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    check = result["checks"][0]
    assert all(step["ok"] for step in check["steps"])
    assert check["status"] == "action_failed"
    assert check["visual_sanity"]["kind"] == "severe_text_contrast"
    assert check["visual_sanity"]["issues"][0]["ratio"] < 1.5


@pytest.mark.anyio
async def test_webcompass_risk_audits_distinguish_eleven_defects_from_fixed_dom(
    tmp_path: Path,
):
    svg = (
        "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' "
        "width='100' height='50'%3E%3Crect width='100' height='50'/%3E%3C/svg%3E"
    )
    page_state = {"fixed": False}

    def html() -> str:
        if not page_state["fixed"]:
            return f"""
            <style>
              #occlusion-wrap {{ position: relative; width: 120px; height: 40px; }}
              #occlusion-cover {{ position: absolute; inset: 0; background: red; z-index: 2; }}
              #crowding {{ display: flex; gap: 0; }}
              #overlap {{ position: relative; height: 30px; }}
              #overlap span {{ position: absolute; left: 0; top: 0; }}
              #alignment {{ display: flex; }} #alignment > :last-child {{ margin-top: 24px; }}
              #contrast {{ color: rgb(120,120,120); background: rgb(130,130,130); }}
              #overflow {{ width: 100px; overflow-x: visible; }} #overflow > div {{ width: 220px; }}
              #loss {{ pointer-events: none; }}
            </style>
            <div id="occlusion-wrap"><button id="occlusion">Open</button><i id="occlusion-cover"></i></div>
            <div id="crowding"><button data-testid="crowd-a">A</button><button data-testid="crowd-b">B</button></div>
            <div id="overlap"><span>First text</span><span>Second text</span></div>
            <div id="alignment"><i>A</i><i>B</i><i>C</i></div>
            <div id="contrast">Unreadable text</div>
            <div id="overflow"><div>wide content</div></div>
            <div id="sizing"><img src="{svg}" style="width:100px;height:100px"></div>
            <button id="loss">Save</button>
            <div id="semantic" onclick="void 0">Open settings</div>
            <div id="nesting"><button>Outer <span role="button">Inner</span></button></div>
            <div id="missing"><img src="{svg}"></div>
            """
        return f"""
        <style>
          #occlusion-wrap {{ position: relative; width: 120px; height: 40px; }}
          #occlusion-cover {{ display: none; }}
          #crowding {{ display: flex; gap: 8px; }}
          #overlap {{ display: flex; gap: 8px; }}
          #alignment {{ display: flex; }}
          #contrast {{ color: black; background: white; }}
          #overflow {{ width: 100px; overflow-x: auto; }} #overflow > div {{ width: 220px; }}
        </style>
        <div id="occlusion-wrap"><button id="occlusion">Open</button><i id="occlusion-cover"></i></div>
        <div id="crowding"><button data-testid="crowd-a">A</button><button data-testid="crowd-b">B</button></div>
        <div id="overlap"><span>First text</span><span>Second text</span></div>
        <div id="alignment"><i>A</i><i>B</i><i>C</i></div>
        <div id="contrast">Readable text</div>
        <div id="overflow"><div>wide content</div></div>
        <div id="sizing"><img alt="chart" src="{svg}" style="width:100px;height:50px"></div>
        <button id="loss">Save</button>
        <button id="semantic">Open settings</button>
        <div id="nesting"><button>Outer</button><button>Inner</button></div>
        <div id="missing"><img alt="preview" src="{svg}"></div>
        """

    async def page(_request):
        return web.Response(text=html(), content_type="text/html")

    checks = [
        {"id": "RISK-OCCLUSION", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#occlusion",
            "defect_type": "Occlusion",
        }]},
        {"id": "RISK-CROWDING", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#crowding",
            "defect_type": "Crowding",
        }]},
        {"id": "RISK-TEXT", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#overlap",
            "defect_type": "Text Overlap",
        }]},
        {"id": "RISK-ALIGNMENT", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#alignment",
            "defect_type": "Alignment",
        }]},
        {"id": "RISK-CONTRAST", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#contrast",
            "defect_type": "Color Contrast",
        }]},
        {"id": "RISK-OVERFLOW", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#overflow",
            "defect_type": "Overflow",
        }]},
        {"id": "RISK-SIZING", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#sizing",
            "defect_type": "Sizing Proportion",
        }]},
        {"id": "RISK-LOSS", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#loss",
            "defect_type": "Loss of Interactivity",
        }]},
        {"id": "RISK-SEMANTIC", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#semantic",
            "defect_type": "Semantic Error",
        }]},
        {"id": "RISK-NESTING", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#nesting",
            "defect_type": "Nesting Error",
        }]},
        {"id": "RISK-MISSING", "route": "/", "actions": [{
            "action": "assert_webcompass_risk", "selector": "#missing",
            "defect_type": "Missing Attributes",
        }]},
    ]
    app = web.Application()
    app.router.add_get("/", page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        broken = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=checks,
            output_path=tmp_path / "eleven-broken.json",
            headless=True,
        )
        page_state["fixed"] = True
        fixed = await collect_browser_evidence(
            app_url=f"http://127.0.0.1:{port}",
            checks=checks,
            output_path=tmp_path / "eleven-fixed.json",
            headless=True,
        )
    finally:
        await runner.cleanup()

    assert [item["status"] for item in broken["checks"]] == ["action_failed"] * 11
    assert [item["status"] for item in fixed["checks"]] == ["ok"] * 11
    assert all(
        item["steps"][0]["output"]["actual"]["issues"]
        for item in broken["checks"]
    )
