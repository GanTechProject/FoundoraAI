from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import cast
from urllib.parse import unquote, urlsplit

from foundora.agents.schema import AgentSchemaError
from foundora.agents.website_coding import WEBSITE_TOOL_IDS, validate_project_path

MAX_FILE_BYTES = 96_000
MAX_PROJECT_BYTES = 512_000
MAX_FILES = 48
_REMOTE_REFERENCE = re.compile(r"(?:https?:)?//", re.IGNORECASE)
_SECRET_MARKER = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:api[_-]?key|secret[_-]?key|password)\s*[=:])",
    re.IGNORECASE,
)
_UNSAFE_JAVASCRIPT = re.compile(
    r"(?:\beval\s*\(|\bFunction\s*\(|\bfetch\s*\(|XMLHttpRequest|WebSocket|document\.cookie|localStorage|sessionStorage)",
    re.IGNORECASE,
)
_CSS_REFERENCE = re.compile(
    r"(?:url\(\s*(['\"]?)(?P<url>[^)'\"]+)\1\s*\)|@import\s+(['\"])(?P<import>[^'\"]+)\3)",
    re.IGNORECASE,
)
_JAVASCRIPT_IMPORT = re.compile(
    r"(?:\bimport\s+(?:[^;]*?\s+from\s+)?|\bexport\s+[^;]*?\s+from\s+)(['\"])(?P<path>[^'\"]+)\1"
)
_VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_ASSET_LINK_RELATIONS = frozenset({"icon", "manifest", "modulepreload", "preload", "stylesheet"})


class ControlledWebsiteToolError(Exception):
    pass


@dataclass(frozen=True)
class WebsiteBuildArtifact:
    source_files: list[dict[str, object]]
    dependency_manifest: dict[str, object]
    source_digest: str
    build_digest: str
    build_manifest: list[dict[str, object]]
    build_report: dict[str, object]
    check_report: dict[str, object]
    tool_audit: list[dict[str, object]]


class _PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang: str | None = None
        self.title_parts: list[str] = []
        self.description: str | None = None
        self.viewport = False
        self.main_count = 0
        self.h1_count = 0
        self.ids: list[str] = []
        self.links: list[str] = []
        self.asset_references: list[str] = []
        self.image_alt_missing = 0
        self._title_depth = 0
        self._anchor_depth = 0
        self._anchor_text: list[str] = []
        self.empty_link_count = 0
        self.text_parts: list[str] = []
        self.syntax_issues: list[str] = []
        self._open_tags: list[str] = []
        self.doctype_count = 0
        self.inline_scripts: list[str] = []
        self.inline_styles: list[str] = []
        self._script_parts: list[str] | None = None
        self._style_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        names = [name for name, _ in attrs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            self.syntax_issues.append(f"duplicate attributes {', '.join(duplicates)}")
        attributes = dict(attrs)
        if tag not in _VOID_HTML_TAGS:
            self._open_tags.append(tag)
        if tag == "html":
            self.lang = attributes.get("lang")
        if tag == "title":
            self._title_depth += 1
        if tag == "meta":
            name = (attributes.get("name") or "").lower()
            if name == "description":
                self.description = attributes.get("content")
            if name == "viewport":
                self.viewport = bool(attributes.get("content"))
        if tag == "main":
            self.main_count += 1
        if tag == "h1":
            self.h1_count += 1
        identifier = attributes.get("id")
        if identifier:
            self.ids.append(identifier)
        if tag == "a":
            self._anchor_depth += 1
            self._anchor_text = []
            href = attributes.get("href")
            if href:
                self.links.append(href)
        if tag == "link":
            relations = set((attributes.get("rel") or "").lower().split())
            href = attributes.get("href")
            if href and relations.intersection(_ASSET_LINK_RELATIONS):
                self.asset_references.append(href)
        if tag in {"script", "img", "source", "video", "audio", "iframe"}:
            source = attributes.get("src")
            if source:
                self.asset_references.append(source)
        if tag == "script" and not attributes.get("src"):
            self._script_parts = []
        if tag == "style":
            self._style_parts = []
        if tag == "video" and attributes.get("poster"):
            self.asset_references.append(cast(str, attributes["poster"]))
        if tag == "object" and attributes.get("data"):
            self.asset_references.append(cast(str, attributes["data"]))
        if tag == "img" and not (attributes.get("alt") or "").strip():
            self.image_alt_missing += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID_HTML_TAGS:
            if not self._open_tags:
                self.syntax_issues.append(f"unexpected closing tag </{tag}>")
            elif self._open_tags[-1] != tag:
                self.syntax_issues.append(
                    f"closing tag </{tag}> does not match <{self._open_tags[-1]}>"
                )
            else:
                self._open_tags.pop()
        if tag == "script" and self._script_parts is not None:
            self.inline_scripts.append("".join(self._script_parts))
            self._script_parts = None
        if tag == "style" and self._style_parts is not None:
            self.inline_styles.append("".join(self._style_parts))
            self._style_parts = None
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag == "a" and self._anchor_depth:
            if not "".join(self._anchor_text).strip():
                self.empty_link_count += 1
            self._anchor_depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_decl(self, decl: str) -> None:
        if decl.strip().casefold() == "doctype html":
            self.doctype_count += 1
        else:
            self.syntax_issues.append("unsupported declaration")

    def finish(self) -> None:
        if self._open_tags:
            self.syntax_issues.append(f"unclosed tag <{self._open_tags[-1]}>")
        if self.doctype_count != 1:
            self.syntax_issues.append("exactly one HTML5 doctype is required")

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._anchor_depth:
            self._anchor_text.append(data)
        if data.strip():
            self.text_parts.append(data)
        if self._script_parts is not None:
            self._script_parts.append(data)
        if self._style_parts is not None:
            self._style_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tree_digest(files: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda value: cast(str, value["path"])):
        digest.update(cast(str, item["path"]).encode())
        digest.update(b"\0")
        digest.update(cast(str, item["sha256"]).encode())
        digest.update(b"\0")
    return digest.hexdigest()


def _media_type(path: str) -> str:
    return {
        ".html": "text/html",
        ".css": "text/css",
        ".js": "text/javascript",
        ".json": "application/json",
        ".txt": "text/plain",
    }[Path(path).suffix.lower()]


def _route_file(route: str) -> str:
    if route == "/":
        return "index.html"
    if (
        not route.startswith("/")
        or "?" in route
        or "#" in route
        or "\\" in route
        or any(part in {"", ".", ".."} for part in route.strip("/").split("/"))
    ):
        raise ControlledWebsiteToolError("The approved sitemap contains an unsafe route")
    return f"{route.strip('/')}/index.html"


def _local_reference(reference: str, source_path: str) -> str | None:
    parsed = urlsplit(reference.strip())
    if parsed.scheme == "data":
        return None
    if parsed.scheme or parsed.netloc:
        raise ControlledWebsiteToolError(f"{source_path}: unsupported asset reference {reference}")
    raw_path = unquote(parsed.path)
    if not raw_path:
        return None
    parts: list[str] = []
    candidates = (
        PurePosixPath(raw_path.lstrip("/")).parts
        if raw_path.startswith("/")
        else (PurePosixPath(source_path).parent / raw_path).parts
    )
    for part in candidates:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise ControlledWebsiteToolError(
                    f"{source_path}: asset reference escapes the project root"
                )
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts)


def _validate_asset_reference(
    reference: str, source_path: str, source_paths: set[str], lint_issues: list[str]
) -> None:
    target = _local_reference(reference, source_path)
    if target is not None and target not in source_paths:
        lint_issues.append(f"{source_path}: referenced asset {reference} does not resolve")


def _css_syntax_issue(value: str) -> str | None:
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    quote: str | None = None
    escaped = False
    in_comment = False
    index = 0
    while index < len(value):
        character = value[index]
        following = value[index + 1] if index + 1 < len(value) else ""
        if in_comment:
            if character == "*" and following == "/":
                in_comment = False
                index += 2
                continue
        elif quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
        elif character == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        elif character in {"'", '"'}:
            quote = character
        elif character in "([{":
            stack.append(character)
        elif character in pairs:
            if not stack or stack.pop() != pairs[character]:
                return "mismatched delimiter"
        index += 1
    if in_comment:
        return "unterminated comment"
    if quote is not None:
        return "unterminated string"
    if stack:
        return "unclosed delimiter"
    if re.search(r"(?:^|[;{])\s*[-\w]+\s*:\s*(?:;|})", value):
        return "empty declaration value"
    return None


def _javascript_syntax_issue(value: str) -> bool:
    try:
        result = subprocess.run(
            ["node", "--check", "--input-type=module"],
            input=value,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        raise ControlledWebsiteToolError(
            "The JavaScript syntax validator is unavailable"
        ) from error
    return result.returncode != 0


class ControlledWebsiteBuilder:
    """Apply declarative file changes and build without executing generated code."""

    def build(
        self, structured_input: dict[str, object], output: dict[str, object]
    ) -> WebsiteBuildArtifact:
        try:
            return self._build(structured_input, output)
        except (AgentSchemaError, UnicodeError, ValueError, OSError) as error:
            raise ControlledWebsiteToolError(str(error)) from error

    def _build(
        self, structured_input: dict[str, object], output: dict[str, object]
    ) -> WebsiteBuildArtifact:
        evidence = structured_input.get("website_coding_evidence")
        if not isinstance(evidence, dict):
            raise ControlledWebsiteToolError("Pinned website coding evidence is missing")
        base = evidence.get("base_project")
        source_by_path: dict[str, dict[str, object]] = {}
        if isinstance(base, dict):
            for index, item in enumerate(base.get("source_files", [])):
                if not isinstance(item, dict) or not isinstance(item.get("content"), str):
                    raise ControlledWebsiteToolError("Base project source tree is invalid")
                path = validate_project_path(item.get("path"), f"$.base_project[{index}].path")
                source_by_path[path] = {
                    "path": path,
                    "media_type": _media_type(path),
                    "content": item["content"],
                }

        changes = output.get("changes")
        if not isinstance(changes, list):
            raise ControlledWebsiteToolError("Controlled source changes are missing")
        for index, change in enumerate(changes):
            if not isinstance(change, dict):
                raise ControlledWebsiteToolError("Controlled source change is invalid")
            path = validate_project_path(change.get("path"), f"$.changes[{index}].path")
            operation = change.get("operation")
            if operation == "delete":
                source_by_path.pop(path)
                continue
            content = change.get("content")
            if not isinstance(content, str):
                raise ControlledWebsiteToolError("Source content must be UTF-8 text")
            declared_media_type = change.get("media_type")
            if declared_media_type != _media_type(path):
                raise ControlledWebsiteToolError("Source media type does not match its path")
            source_by_path[path] = {
                "path": path,
                "media_type": declared_media_type,
                "content": content,
            }

        if not source_by_path or len(source_by_path) > MAX_FILES:
            raise ControlledWebsiteToolError("Website source tree exceeds its file-count boundary")
        source_files: list[dict[str, object]] = []
        total_bytes = 0
        for path, item in sorted(source_by_path.items()):
            content = cast(str, item["content"])
            encoded = content.encode("utf-8")
            if not encoded or len(encoded) > MAX_FILE_BYTES:
                raise ControlledWebsiteToolError(f"{path} exceeds its source-size boundary")
            if _REMOTE_REFERENCE.search(content):
                raise ControlledWebsiteToolError(f"{path} contains an external network reference")
            if _SECRET_MARKER.search(content):
                raise ControlledWebsiteToolError(f"{path} resembles embedded credential material")
            if path.endswith(".json"):
                json.loads(content)
            total_bytes += len(encoded)
            source_files.append(
                {
                    **item,
                    "size_bytes": len(encoded),
                    "sha256": _sha256(encoded),
                }
            )
        if total_bytes > MAX_PROJECT_BYTES:
            raise ControlledWebsiteToolError("Website source tree exceeds its total-size boundary")

        specification = evidence.get("approved_website_specification")
        if not isinstance(specification, dict):
            raise ControlledWebsiteToolError("Approved website specification is missing")
        pages = specification.get("sitemap")
        if not isinstance(pages, list):
            raise ControlledWebsiteToolError("Approved sitemap is missing")
        route_files: dict[str, str] = {}
        for page in pages:
            if not isinstance(page, dict) or not isinstance(page.get("path"), str):
                raise ControlledWebsiteToolError("Approved sitemap page is invalid")
            route_file = _route_file(page["path"])
            if route_file not in source_by_path:
                raise ControlledWebsiteToolError(
                    f"Sitemap route {page['path']} has no generated HTML document"
                )
            route_files[page["path"]] = route_file

        inspectors: dict[str, _PageInspector] = {}
        lint_issues: list[str] = []
        accessibility_issues: list[str] = []
        seo_issues: list[str] = []
        for route, path in route_files.items():
            content = cast(str, source_by_path[path]["content"])
            inspector = _PageInspector()
            inspector.feed(content)
            inspector.close()
            inspector.finish()
            inspectors[route] = inspector
            if inspector.syntax_issues:
                lint_issues.append(f"{path}: malformed HTML ({inspector.syntax_issues[0]})")
            duplicates = sorted({item for item in inspector.ids if inspector.ids.count(item) > 1})
            if duplicates:
                lint_issues.append(f"{path}: duplicate ids {', '.join(duplicates)}")
            if not inspector.lang:
                accessibility_issues.append(f"{path}: html lang is missing")
            if not inspector.viewport:
                accessibility_issues.append(f"{path}: viewport metadata is missing")
            if inspector.main_count != 1:
                accessibility_issues.append(f"{path}: exactly one main landmark is required")
            if inspector.h1_count != 1:
                accessibility_issues.append(f"{path}: exactly one h1 is required")
            if inspector.image_alt_missing:
                accessibility_issues.append(f"{path}: every image requires alt text")
            if inspector.empty_link_count:
                accessibility_issues.append(f"{path}: links require accessible text")
            if not inspector.title:
                seo_issues.append(f"{path}: title is missing")
            if not (inspector.description or "").strip():
                seo_issues.append(f"{path}: meta description is missing")
            for href in inspector.links:
                if href.startswith(("#", "mailto:", "tel:")):
                    continue
                target = href.split("#", 1)[0].rstrip("/") or "/"
                if target.startswith("/") and target not in route_files:
                    lint_issues.append(f"{path}: internal link {href} does not resolve")

        source_paths = set(source_by_path)
        for path, inspector in ((route_files[route], item) for route, item in inspectors.items()):
            for reference in inspector.asset_references:
                _validate_asset_reference(reference, path, source_paths, lint_issues)
            for script in inspector.inline_scripts:
                if _javascript_syntax_issue(script):
                    lint_issues.append(f"{path}: invalid inline JavaScript syntax")
            for style in inspector.inline_styles:
                if issue := _css_syntax_issue(style):
                    lint_issues.append(f"{path}: invalid inline CSS ({issue})")
                for match in _CSS_REFERENCE.finditer(style):
                    reference = match.group("url") or match.group("import")
                    _validate_asset_reference(reference, path, source_paths, lint_issues)

        for item in source_files:
            path = cast(str, item["path"])
            content = cast(str, item["content"])
            if path.endswith(".css"):
                if issue := _css_syntax_issue(content):
                    lint_issues.append(f"{path}: invalid CSS syntax ({issue})")
                for match in _CSS_REFERENCE.finditer(content):
                    reference = match.group("url") or match.group("import")
                    _validate_asset_reference(reference, path, source_paths, lint_issues)
            if path.endswith(".js"):
                if _javascript_syntax_issue(content):
                    lint_issues.append(f"{path}: invalid JavaScript syntax")
                if _UNSAFE_JAVASCRIPT.search(content):
                    lint_issues.append(f"{path}: disallowed dynamic or network JavaScript")
                for match in _JAVASCRIPT_IMPORT.finditer(content):
                    _validate_asset_reference(match.group("path"), path, source_paths, lint_issues)

        titles = [item.title.casefold() for item in inspectors.values()]
        descriptions = [(item.description or "").strip().casefold() for item in inspectors.values()]
        if len(titles) != len(set(titles)):
            seo_issues.append("Page titles must be unique")
        if len(descriptions) != len(set(descriptions)):
            seo_issues.append("Page meta descriptions must be unique")

        test_issues: list[str] = []
        test_cases = output.get("test_cases")
        if not isinstance(test_cases, list):
            raise ControlledWebsiteToolError("Generated tests are missing")
        assertions_run = 0
        for case in test_cases:
            if not isinstance(case, dict) or not isinstance(case.get("page_path"), str):
                raise ControlledWebsiteToolError("Generated test case is invalid")
            route = case["page_path"]
            test_inspector = inspectors.get(route)
            if test_inspector is None:
                test_issues.append(f"Test route {route} does not exist")
                continue
            assertions = case.get("assertions")
            if not isinstance(assertions, list) or not assertions:
                test_issues.append(f"Test route {route} has no assertions")
                continue
            for assertion in assertions:
                assertions_run += 1
                if not isinstance(assertion, dict):
                    test_issues.append(f"Test route {route} has an invalid assertion")
                    continue
                kind = assertion.get("kind")
                value = assertion.get("value")
                if not isinstance(value, str) or not value:
                    test_issues.append(f"Test route {route} has an empty assertion value")
                elif (
                    kind == "contains_text"
                    and value.casefold() not in test_inspector.text.casefold()
                ):
                    test_issues.append(f"Test route {route} is missing expected text")
                elif kind == "element_id" and value not in test_inspector.ids:
                    test_issues.append(f"Test route {route} is missing expected element id")
                elif kind == "link_target" and value not in test_inspector.links:
                    test_issues.append(f"Test route {route} is missing expected link target")
                elif (
                    kind == "meta_description"
                    and value.casefold() not in (test_inspector.description or "").casefold()
                ):
                    test_issues.append(f"Test route {route} has unexpected metadata")
                elif kind not in {
                    "contains_text",
                    "element_id",
                    "link_target",
                    "meta_description",
                }:
                    test_issues.append(f"Test route {route} uses an unsupported assertion")

        issues = lint_issues + accessibility_issues + seo_issues + test_issues
        if issues:
            raise ControlledWebsiteToolError(f"Controlled website checks failed: {issues[0]}")

        build_manifest: list[dict[str, object]] = []
        with TemporaryDirectory(prefix="foundora-website-build-") as temporary:
            root = Path(temporary)
            source_root = root / "source"
            build_root = root / "build"
            for item in source_files:
                relative = cast(str, item["path"])
                destination = source_root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(cast(str, item["content"]), encoding="utf-8", newline="\n")
            shutil.copytree(source_root, build_root)
            for file_path in sorted(path for path in build_root.rglob("*") if path.is_file()):
                relative = file_path.relative_to(build_root).as_posix()
                value = file_path.read_bytes()
                build_manifest.append(
                    {"path": relative, "size_bytes": len(value), "sha256": _sha256(value)}
                )

        source_digest = _tree_digest(source_files)
        build_digest = _tree_digest(build_manifest)
        categories = {
            "tests": {"status": "passed", "assertions_run": assertions_run},
            "lint": {"status": "passed", "files_checked": len(source_files)},
            "accessibility": {"status": "passed", "pages_checked": len(route_files)},
            "technical_seo": {"status": "passed", "pages_checked": len(route_files)},
            "performance": {
                "status": "passed",
                "total_bytes": total_bytes,
                "maximum_total_bytes": MAX_PROJECT_BYTES,
                "maximum_file_bytes": MAX_FILE_BYTES,
            },
        }
        return WebsiteBuildArtifact(
            source_files=source_files,
            dependency_manifest=cast(dict[str, object], output["dependency_manifest"]),
            source_digest=source_digest,
            build_digest=build_digest,
            build_manifest=build_manifest,
            build_report={
                "status": "passed",
                "builder": "foundora.controlled-static-build@2",
                "source_file_count": len(source_files),
                "build_file_count": len(build_manifest),
                "source_digest": source_digest,
                "build_digest": build_digest,
            },
            check_report={"status": "passed", "categories": categories},
            tool_audit=[
                {"tool_id": WEBSITE_TOOL_IDS[0], "operation": "checkout", "status": "passed"},
                {"tool_id": WEBSITE_TOOL_IDS[1], "operation": "apply_changes", "status": "passed"},
                {
                    "tool_id": WEBSITE_TOOL_IDS[2],
                    "operation": "resolve_manifest",
                    "status": "passed",
                },
                {"tool_id": WEBSITE_TOOL_IDS[0], "operation": "build", "status": "passed"},
                {"tool_id": WEBSITE_TOOL_IDS[3], "operation": "verify", "status": "passed"},
            ],
        )
