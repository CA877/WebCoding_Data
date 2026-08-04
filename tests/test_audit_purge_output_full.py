from pathlib import Path
import sys

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

from scripts.audit_purge_output_full import apply_audit, inspect_site


def _page(site: Path, name: str, text: str, *, screenshot: bool = True) -> None:
    content = " ".join([text] * 8)
    (site / name).write_text(f"<html lang='en'><head><title>Useful app</title></head><body><main>{content}</main></body></html>")
    if screenshot:
        target = site / ("screenshot.png" if name == "index.html" else f"{Path(name).stem}_screenshot.png")
        image = Image.new("RGB", (800, 600), "white")
        for x in range(100, 700):
            for y in range(100, 500):
                image.putpixel((x, y), (30, 100 + x % 100, 180))
        image.save(target)


def test_one_bad_child_rejects_whole_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "A useful dashboard with navigation, reports, settings, and project summaries.")
    _page(site, "bad.html", "Online casino slot machine and sports betting offers.")
    result = inspect_site(site)
    assert result["status"] == "reject"
    assert result["failed_page_count"] == 1
    assert result["reasons"]["unsafe_content"] == 1


def test_missing_child_screenshot_rejects_whole_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "A useful dashboard with navigation, reports, settings, and project summaries.")
    _page(site, "details.html", "Detailed project information with tasks, owners, progress, and recent activity.", screenshot=False)
    result = inspect_site(site)
    assert result["status"] == "reject"
    assert result["reasons"]["missing_screenshot"] == 1


def test_all_healthy_pages_pass(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "A useful dashboard with navigation, reports, settings, and project summaries.")
    _page(site, "details.html", "Detailed project information with tasks, owners, progress, and recent activity.")
    assert inspect_site(site)["status"] == "pass"


def test_contextual_access_denied_phrase_does_not_reject_product_page(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(
        site,
        "index.html",
        "Identity management helps employees avoid access denied errors while using business applications.",
    )
    assert inspect_site(site)["status"] == "pass"


def test_captcha_product_copy_does_not_reject_product_page(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(
        site,
        "index.html",
        "Our identity security platform includes CAPTCHA protection, authentication, reporting, and access controls.",
    )
    assert inspect_site(site)["status"] == "pass"


def test_link_heavy_legitimate_directory_is_review_only(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    links = " ".join(f"<a href='/recipe/{i}'>Recipe number {i}</a>" for i in range(80))
    _page(site, "index.html", links)
    result = inspect_site(site)
    assert result["status"] == "pass"
    assert result["warnings"]["link_farm_or_directory_page"] == 1


def test_contextual_safety_terms_are_review_only(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "Government investigators combat child pornography and protect children.")
    _page(site, "policy.html", "Park rules prohibit disorderly behavior and illegal drugs for visitor safety.")
    result = inspect_site(site)
    assert result["status"] == "pass"
    assert result["warnings"]["contextual_adult_term"] == 1
    assert result["warnings"]["contextual_drug_term"] == 1


def test_foreign_language_is_selection_metadata_not_quality_failure(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "Eine vollständige Projektseite mit Navigation, Berichten und Einstellungen.")
    html = (site / "index.html").read_text().replace("lang='en'", "lang='de'")
    (site / "index.html").write_text(html)
    result = inspect_site(site)
    assert result["status"] == "pass"
    assert result["warnings"]["unsupported_language"] == 1


def test_phone_placeholder_and_gambling_disclaimer_are_review_only(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "Contact our office by phone at xxx-xxx-xxxx for assistance.")
    _page(site, "policy.html", "We do not provide links to sports betting websites or related services.")
    result = inspect_site(site)
    assert result["status"] == "pass"
    assert result["warnings"]["contextual_adult_term"] == 1
    assert result["warnings"]["contextual_gambling_term"] == 1


def test_repeated_explicit_adult_listing_rejects_site(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "Watch amateur-porn videos and gay-porn listings online now.")
    assert inspect_site(site)["status"] == "reject"


def test_prohibited_content_policy_is_review_only(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _page(site, "index.html", "Terms of service: prohibited content includes pornographic files and porn uploads.")
    assert inspect_site(site)["status"] == "pass"


def test_apply_audit_deletes_only_rejected_sites(tmp_path: Path) -> None:
    root = tmp_path / "sites"
    keep, drop = root / "keep", root / "drop"
    keep.mkdir(parents=True); drop.mkdir()
    (keep / "data").write_text("keep")
    (drop / "data").write_text("drop")
    audit = tmp_path / "audit.jsonl"
    audit.write_text("\n".join([
        json.dumps({"site": "keep", "status": "pass", "reasons": {}}),
        json.dumps({"site": "drop", "status": "reject", "reasons": {"unsafe_content": 1}}),
    ]) + "\n")
    result = apply_audit(root, audit, tmp_path / "deleted.jsonl")
    assert result["deleted"] == 1
    assert keep.exists()
    assert not drop.exists()
