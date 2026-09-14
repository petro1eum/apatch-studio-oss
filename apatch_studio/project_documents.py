"""Bounded repository knowledge with no executable Markdown projection."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

from apatch.spec import _load_spec
from apatch.spec_interference import _discover_spec_ids


MAX_DOCUMENTS = 250
MAX_DOCUMENT_BYTES = 512_000
MAX_BLOCKS = 600
MAX_BLOCK_TEXT = 4_000
MAX_PURPOSE_TEXT = 1_200
_RFP_ID_PATTERN = r"(?:RFP-[0-9]{3}|RFP-STUDIO-[0-9A-F]{12})"
_DOCUMENT_ID = re.compile(
    rf"^(?:PROJECT-README|{_RFP_ID_PATTERN}|SPEC-[A-Z0-9][A-Z0-9-]{{1,120}})$"
)
_RFP_FILE = re.compile(rf"^({_RFP_ID_PATTERN})-[A-Za-z0-9._-]+[.]md$")
_SPEC_FILE = re.compile(r"^(SPEC-[A-Z0-9][A-Z0-9-]{1,120})[.]md$")
_REQUIREMENT_HEADING = re.compile(r"^(R[0-9]+)\s+(.+)$")
_METADATA = re.compile(r"^>\s*[*][*]([^*]+):[*][*]\s*(.*?)\s*$", re.MULTILINE)
_ANCHOR = re.compile(rf"[*][*]Anchors:[*][*]\s*({_RFP_ID_PATTERN})")
_UNSAFE_HTML = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_ESCAPED_TABLE_BREAK = re.compile(r"(?<=\|)\\n(?:\r?\n)?(?=\|)")


class InvalidProjectDocumentId(ValueError):
    pass


class ProjectDocumentNotFound(LookupError):
    pass


def _bounded_text(value: str, limit: int = MAX_BLOCK_TEXT) -> str:
    normalized = unicodedata.normalize("NFC", value)
    normalized = "".join(char for char in normalized if char in "\n\t" or ord(char) >= 32)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized).strip()
    return normalized[:limit]


def _inline_text(token: Any) -> str:
    parts: list[str] = []
    for child in token.children or []:
        if child.type in {"text", "code_inline"}:
            parts.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
    return _bounded_text("".join(parts))


def _parse_list(tokens: list[Any], start: int) -> tuple[dict[str, Any], int]:
    opening = tokens[start].type
    closing = "ordered_list_close" if opening == "ordered_list_open" else "bullet_list_close"
    ordered = opening == "ordered_list_open"
    depth = 1
    in_item = 0
    parts: list[str] = []
    items: list[str] = []
    index = start + 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == opening:
            depth += 1
        elif token.type == closing:
            depth -= 1
            if depth == 0:
                break
        elif token.type == "list_item_open" and depth == 1:
            in_item += 1
            parts = []
        elif token.type == "list_item_close" and depth == 1 and in_item:
            text = _bounded_text(" ".join(part for part in parts if part))
            if text:
                items.append(text)
            in_item -= 1
        elif token.type == "inline" and in_item:
            text = _inline_text(token)
            if text:
                parts.append(text)
        index += 1
    return {"type": "list", "ordered": ordered, "items": items[:100]}, index + 1


def _parse_table(tokens: list[Any], start: int) -> tuple[dict[str, Any], int]:
    rows: list[list[str]] = []
    row: list[str] | None = None
    cell: list[str] | None = None
    index = start + 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_close":
            break
        if token.type == "tr_open":
            row = []
        elif token.type in {"th_open", "td_open"}:
            cell = []
        elif token.type == "inline" and cell is not None:
            cell.append(_inline_text(token))
        elif token.type in {"th_close", "td_close"} and row is not None and cell is not None:
            row.append(_bounded_text(" ".join(cell), 2_000))
            cell = None
        elif token.type == "tr_close" and row is not None:
            rows.append(row[:20])
            row = None
        index += 1
    return {"type": "table", "headers": rows[0] if rows else [], "rows": rows[1:101]}, index + 1


def parse_markdown_blocks(source: str) -> list[dict[str, Any]]:
    """Parse Markdown to a bounded, non-executable content projection."""

    safe_source = _UNSAFE_HTML.sub("", source[:MAX_DOCUMENT_BYTES])
    safe_source = _ESCAPED_TABLE_BREAK.sub("\n", safe_source)
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(safe_source)
    blocks: list[dict[str, Any]] = []
    quote_depth = 0
    index = 0
    while index < len(tokens) and len(blocks) < MAX_BLOCKS:
        token = tokens[index]
        if token.type == "blockquote_open":
            quote_depth += 1
            index += 1
            continue
        if token.type == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
            index += 1
            continue
        if token.type == "heading_open" and index + 1 < len(tokens):
            text = _inline_text(tokens[index + 1])
            if text:
                blocks.append({"type": "heading", "level": int(token.tag[1:]), "text": text})
            index += 3
            continue
        if token.type == "paragraph_open" and index + 1 < len(tokens):
            text = _inline_text(tokens[index + 1])
            if text:
                blocks.append({"type": "quote" if quote_depth else "paragraph", "text": text})
            index += 3
            continue
        if token.type in {"bullet_list_open", "ordered_list_open"}:
            block, index = _parse_list(tokens, index)
            if block["items"]:
                blocks.append(block)
            continue
        if token.type == "table_open":
            block, index = _parse_table(tokens, index)
            if block["headers"]:
                blocks.append(block)
            continue
        if token.type in {"fence", "code_block"}:
            info_parts = (token.info or "").split()
            language = _bounded_text(info_parts[0], 40) if info_parts else ""
            blocks.append(
                {
                    "type": "code",
                    "language": language or None,
                    "text": _bounded_text(token.content),
                }
            )
        elif token.type == "hr":
            blocks.append({"type": "divider"})
        index += 1
    return blocks


def _sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"title": "Overview", "blocks": []}
    for block in blocks:
        if block.get("type") == "heading" and block.get("level") == 2:
            if current["blocks"]:
                sections.append(current)
            current = {"title": block["text"], "blocks": []}
        elif not (block.get("type") == "heading" and block.get("level") == 1):
            current["blocks"].append(block)
    if current["blocks"]:
        sections.append(current)
    return sections[:80]


def _section_key(value: str) -> str:
    return re.sub(r"^[0-9]+(?:[.][0-9]+)*[.]?\s*", "", value).strip().casefold()


def _find_section(sections: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    wanted = name.casefold()
    return next((section for section in sections if _section_key(section["title"]) == wanted), None)


def _block_text(block: dict[str, Any]) -> str:
    if block.get("type") in {"paragraph", "quote", "code"}:
        return str(block.get("text") or "")
    if block.get("type") == "list":
        return " ".join(str(item) for item in block.get("items") or [])
    return ""


def _first_prose(section: dict[str, Any] | None) -> str:
    if section is None:
        return ""
    for block in section.get("blocks") or []:
        text = _block_text(block)
        if text and not text.startswith("("):
            return _bounded_text(text, MAX_PURPOSE_TEXT)
    return ""


def _human_title(document_id: str, raw_title: str) -> str:
    title = re.sub(rf"^{re.escape(document_id)}\s*(?:--|—|:|-)\s*", "", raw_title).strip()
    return title or document_id


def _catalog_purpose(value: str) -> str:
    summary = _bounded_text(value, MAX_PURPOSE_TEXT)
    replacements = {
        r"\bsession_token\b": "one-time session authorization",
        r"\bsession_capability\b": "session authorization",
        r"\bprivate_key\b": "private signing material",
        r"\baccess_token\b": "access authorization",
    }
    for pattern, replacement in replacements.items():
        summary = re.sub(pattern, replacement, summary, flags=re.IGNORECASE)
    return summary


def _metadata(source: str) -> dict[str, str]:
    return {key.strip().casefold().replace(" ", "_"): _bounded_text(value, 500) for key, value in _METADATA.findall(source[:40_000])}


def _table_records(block: dict[str, Any]) -> list[dict[str, str]]:
    headers = [str(value).strip().casefold().replace(" ", "_") for value in block.get("headers") or []]
    return [{header: str(row[index]) if index < len(row) else "" for index, header in enumerate(headers)} for row in block.get("rows") or []]


def _document_hash(source: str) -> str:
    return "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest()


class ProjectKnowledgeWorkspace:
    """Read repository-owned project knowledge without creating another source of truth."""

    def __init__(self, workspace: str | Path):
        self.root = Path(workspace).expanduser().resolve()

    def _safe_read(self, path: Path) -> str:
        if path.is_symlink():
            raise ProjectDocumentNotFound("symlinked project documents are not readable")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ProjectDocumentNotFound("project document not found")
        if resolved.stat().st_size > MAX_DOCUMENT_BYTES:
            raise ProjectDocumentNotFound("project document exceeds the reader limit")
        return resolved.read_text(encoding="utf-8")

    def _registry(self) -> dict[str, Path]:
        candidates: list[tuple[str, Path]] = []
        readme = self.root / "README.md"
        if readme.is_file() and not readme.is_symlink():
            candidates.append(("PROJECT-README", readme))
        docs = self.root / "docs"
        if docs.is_dir():
            for path in sorted(docs.glob("RFP-*.md")):
                match = _RFP_FILE.fullmatch(path.name)
                if match and not path.is_symlink():
                    candidates.append((match.group(1), path))
        specs = docs / "specs"
        discoverable_specs = set(_discover_spec_ids(str(self.root)))
        if specs.is_dir():
            for path in sorted(specs.glob("SPEC-*.md")):
                match = _SPEC_FILE.fullmatch(path.name)
                if (
                    match
                    and match.group(1) in discoverable_specs
                    and not path.is_symlink()
                ):
                    candidates.append((match.group(1), path))
        return dict(candidates[:MAX_DOCUMENTS])

    @staticmethod
    def _status_map(status: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        return {str(row.get("id")): row for row in ((status or {}).get("specs") or []) if row.get("id")}

    def project_brief(self) -> dict[str, Any]:
        path = self._registry().get("PROJECT-README")
        if path is None:
            return {"schema": "apatch.studio.project-brief.v1", "title": self.root.name, "purpose": "This repository does not yet provide a project description.", "highlights": [], "description_missing": True, "document_id": None}
        source = self._safe_read(path)
        blocks = parse_markdown_blocks(source)
        title_block = next((block for block in blocks if block.get("type") == "heading" and block.get("level") == 1), None)
        purpose = next((str(block.get("text")) for block in blocks if block.get("type") == "paragraph"), "")
        first_list = next((block for block in blocks if block.get("type") == "list"), None)
        return {"schema": "apatch.studio.project-brief.v1", "title": (title_block or {}).get("text") or self.root.name, "purpose": _bounded_text(purpose, MAX_PURPOSE_TEXT) or "This repository does not yet provide a project description.", "highlights": list((first_list or {}).get("items") or [])[:4], "description_missing": not bool(purpose), "document_id": "PROJECT-README"}

    def _rfp_summary(self, document_id: str, path: Path) -> dict[str, Any]:
        source = self._safe_read(path)
        blocks = parse_markdown_blocks(source)
        sections = _sections(blocks)
        title_block = next((block for block in blocks if block.get("type") == "heading" and block.get("level") == 1), {})
        decision = _find_section(sections, "Decision")
        acceptance_section = _find_section(sections, "Acceptance")
        acceptance_table = next((block for block in (acceptance_section or {}).get("blocks", []) if block.get("type") == "table"), None)
        acceptance = []
        if acceptance_table:
            for row in _table_records(acceptance_table):
                acceptance.append({"id": row.get("id") or "", "requirement": row.get("requirement") or "", "level": row.get("level") or ""})
        return {"id": document_id, "title": _human_title(document_id, str(title_block.get("text") or document_id)), "purpose": _first_prose(decision) or next((_block_text(block) for block in blocks if block.get("type") == "paragraph"), ""), "status": _metadata(source).get("status") or "Status not recorded", "sections": sections, "acceptance": acceptance, "document_hash": _document_hash(source), "byte_count": len(source.encode("utf-8"))}

    def _spec_summary(self, document_id: str, path: Path) -> dict[str, Any]:
        source = self._safe_read(path)
        blocks = parse_markdown_blocks(source)
        sections = _sections(blocks)
        parsed = _load_spec(str(self.root), spec=document_id)
        statements: dict[str, str] = {}
        for section in sections:
            matched = _REQUIREMENT_HEADING.fullmatch(section["title"])
            if not matched:
                continue
            prose = [_block_text(block) for block in section.get("blocks") or [] if _block_text(block) and not _block_text(block).startswith("(verify:")]
            statements[matched.group(1)] = _bounded_text(" ".join(prose), MAX_PURPOSE_TEXT)
        anchor = _ANCHOR.search(source[:20_000])
        trace_section = next(
            (
                section
                for section in sections
                if "rfp traceability" in section["title"].casefold()
            ),
            None,
        )
        trace_table = next((block for block in (trace_section or {}).get("blocks", []) if block.get("type") == "table"), None)
        mappings = []
        if trace_table:
            for row in _table_records(trace_table):
                mappings.append({"acceptance_id": row.get("rfp_id") or "", "requirement_id": row.get("spec_rk") or "", "disposition": row.get("disposition") or ""})
        requirements = []
        for requirement in parsed.requirements:
            statement = statements.get(requirement.id)
            if requirement.id == "R0":
                statement = "This plan is explicitly linked to its proposal and acceptance criteria."
            requirements.append(
                {
                    "id": requirement.id,
                    "title": requirement.title,
                    "statement": statement or requirement.title,
                    "verify": requirement.verify,
                    "content_hash": requirement.content_hash,
                }
            )
        return {"id": document_id, "title": _human_title(document_id, parsed.title), "proposal_id": anchor.group(1) if anchor else None, "status": _metadata(source).get("status") or "Status not recorded", "sections": sections, "requirements": requirements, "mappings": mappings, "document_hash": _document_hash(source), "byte_count": len(source.encode("utf-8"))}

    @staticmethod
    def _plan_state(spec_status: dict[str, Any] | None) -> tuple[str, str]:
        if not spec_status:
            return "planned", "Planned"
        summary = spec_status.get("summary") or {}
        if spec_status.get("coverage_status") == "unavailable":
            return "unavailable", "Status unavailable"
        if int(summary.get("blocked") or 0):
            return "blocked", "Blocked"
        if int(summary.get("stale") or 0):
            return "needs_recheck", "Needs re-check"
        if spec_status.get("done"):
            return "complete", "Complete"
        if int(summary.get("attested") or 0):
            return "in_progress", "In progress"
        return "planned", "Planned"

    def catalog(self, status: dict[str, Any] | None = None) -> dict[str, Any]:
        registry = self._registry()
        status_map = self._status_map(status)
        rfps = {document_id: self._rfp_summary(document_id, path) for document_id, path in registry.items() if document_id.startswith("RFP-")}
        specs = {document_id: self._spec_summary(document_id, path) for document_id, path in registry.items() if document_id.startswith("SPEC-")}
        paired_rfps: set[str] = set()
        items: list[dict[str, Any]] = []
        for spec_id, spec in specs.items():
            rfp_id = spec.get("proposal_id")
            rfp = rfps.get(str(rfp_id)) if rfp_id else None
            if rfp:
                paired_rfps.add(str(rfp_id))
            raw_status = status_map.get(spec_id)
            summary = (raw_status or {}).get("summary") or {}
            state, state_label = self._plan_state(raw_status)
            total = int(summary.get("total") or len(spec["requirements"]))
            complete = int(summary.get("attested") or 0)
            items.append({"id": spec_id, "spec_id": spec_id, "proposal_id": rfp_id if rfp else None, "title": (rfp or spec)["title"], "purpose": _catalog_purpose((rfp or {}).get("purpose") or next((row["statement"] for row in spec["requirements"] if row["id"] != "R0"), "Executable project plan")), "state": state, "state_label": state_label, "progress": {"complete": complete, "total": total, "percent": round(100.0 * complete / total, 1) if total else 0.0}, "next_requirement_id": next((str(row.get("id")) for row in (raw_status or {}).get("requirements") or [] if row.get("state") in {"stale", "pending"}), None), "open_document_id": spec_id})
        for rfp_id, rfp in rfps.items():
            if rfp_id not in paired_rfps:
                items.append({"id": rfp_id, "spec_id": None, "proposal_id": rfp_id, "title": rfp["title"], "purpose": _catalog_purpose(rfp["purpose"]), "state": "proposal", "state_label": "Proposal", "progress": {"complete": 0, "total": len(rfp["acceptance"]), "percent": 0.0}, "next_requirement_id": None, "open_document_id": rfp_id})
        items.sort(key=lambda item: item["proposal_id"] or item["spec_id"] or "", reverse=True)
        return {"schema": "apatch.studio.project-plans.v1", "count": len(items), "items": items[:MAX_DOCUMENTS]}

    @staticmethod
    def _traceability(rfp: dict[str, Any] | None, spec: dict[str, Any]) -> dict[str, Any]:
        acceptance_ids = {row["id"] for row in (rfp or {}).get("acceptance") or [] if row["id"]}
        requirement_ids = {row["id"] for row in spec["requirements"]}
        pairs = [(row["acceptance_id"], row["requirement_id"]) for row in spec["mappings"] if row["disposition"].casefold() == "covered"]
        duplicate_acceptance = {value for value in acceptance_ids if sum(1 for pair in pairs if pair[0] == value) > 1}
        duplicate_requirements = {value for value in requirement_ids if value != "R0" and sum(1 for pair in pairs if pair[1] == value) > 1}
        missing_acceptance = sorted(acceptance_ids - {pair[0] for pair in pairs})
        invalid = sorted({f"{left}->{right}" for left, right in pairs if left not in acceptance_ids or right not in requirement_ids})
        state = "ambiguous" if duplicate_acceptance or duplicate_requirements else "missing" if missing_acceptance or invalid or (rfp is None and pairs) else "complete"
        return {"status": state, "mappings": [{"acceptance_id": left, "requirement_id": right} for left, right in pairs], "missing_acceptance_ids": missing_acceptance, "ambiguous_acceptance_ids": sorted(duplicate_acceptance), "ambiguous_requirement_ids": sorted(duplicate_requirements), "invalid_links": invalid}

    def document(self, document_id: str, status: dict[str, Any] | None = None) -> dict[str, Any]:
        if not _DOCUMENT_ID.fullmatch(document_id):
            raise InvalidProjectDocumentId(document_id)
        registry = self._registry()
        path = registry.get(document_id)
        if path is None:
            raise ProjectDocumentNotFound(document_id)
        if document_id == "PROJECT-README":
            source = self._safe_read(path)
            brief = self.project_brief()
            return {"schema": "apatch.studio.project-document.v1", "id": document_id, "kind": "project_brief", "title": brief["title"], "summary": brief["purpose"], "sections": _sections(parse_markdown_blocks(source)), "technical": {"document_hash": _document_hash(source), "byte_count": len(source.encode("utf-8"))}}
        if document_id.startswith("RFP-"):
            rfp = self._rfp_summary(document_id, path)
            catalog = self.catalog(status)["items"]
            paired_specs = [row["spec_id"] for row in catalog if row.get("proposal_id") == document_id and row.get("spec_id")]
            mappings: dict[str, list[str]] = {}
            for spec_id in paired_specs:
                spec = self._spec_summary(spec_id, registry[spec_id])
                for row in spec["mappings"]:
                    mappings.setdefault(row["acceptance_id"], []).append(row["requirement_id"])
            return {"schema": "apatch.studio.project-document.v1", "id": document_id, "kind": "proposal", "title": rfp["title"], "summary": rfp["purpose"], "status": rfp["status"], "sections": rfp["sections"], "acceptance": [{**row, "requirement_ids": mappings.get(row["id"], [])} for row in rfp["acceptance"]], "paired_spec_ids": paired_specs, "technical": {"document_hash": rfp["document_hash"], "byte_count": rfp["byte_count"]}}
        spec = self._spec_summary(document_id, path)
        rfp_id = spec.get("proposal_id")
        rfp = self._rfp_summary(rfp_id, registry[rfp_id]) if rfp_id in registry else None
        traceability = self._traceability(rfp, spec)
        acceptance = {row["id"]: row for row in (rfp or {}).get("acceptance") or []}
        mapped = {row["requirement_id"]: acceptance.get(row["acceptance_id"]) for row in traceability["mappings"]}
        raw_spec_status = self._status_map(status).get(document_id) or {}
        _plan_state, plan_status_label = self._plan_state(raw_spec_status)
        requirement_status = {str(row.get("id")): row for row in raw_spec_status.get("requirements") or []}
        requirements = []
        for row in spec["requirements"]:
            current = requirement_status.get(row["id"]) or {}
            state = str(current.get("state") or "pending")
            if state == "attested":
                outcome, label = "passed_and_recorded", "Passed and recorded"
            elif state == "stale":
                outcome, label = "needs_recheck", "Needs re-check"
            elif state == "blocked":
                outcome, label = "blocked", "Blocked"
            else:
                outcome, label = "not_run", "Not run yet"
            criterion = mapped.get(row["id"])
            requirements.append({"id": row["id"], "title": row["title"], "statement": row["statement"], "state": state, "state_label": label, "acceptance": criterion, "verification": {"outcome": outcome, "label": label, "explanation": "The configured check passed and APatch recorded signed proof for this exact requirement." if state == "attested" else "This requirement needs its configured check to pass before Studio can call it proven."}, "available_action": "recheck" if state == "stale" else "run" if state == "pending" else "inspect_proof", "technical": {"content_hash": row["content_hash"], "verification_command": row["verify"]}})
        summary = (rfp or {}).get("purpose") or next(
            (row["statement"] for row in requirements if row["id"] != "R0"),
            "Executable project plan",
        )
        return {"schema": "apatch.studio.project-document.v1", "id": document_id, "kind": "specification", "title": spec["title"], "summary": summary, "status": plan_status_label, "proposal_id": rfp_id, "requirements": requirements, "traceability": traceability, "technical": {"document_hash": spec["document_hash"], "byte_count": spec["byte_count"]}}

    def decision_basis(self, spec_id: str, requirement_id: str, status: dict[str, Any] | None = None) -> dict[str, Any] | None:
        try:
            document = self.document(spec_id, status)
        except (InvalidProjectDocumentId, ProjectDocumentNotFound, FileNotFoundError, ValueError):
            return None
        requirement = next((row for row in document.get("requirements") or [] if row["id"] == requirement_id), None)
        if requirement is None:
            return None
        proposal_id = document.get("proposal_id")
        proposal_title = None
        if proposal_id:
            try:
                proposal_title = self.document(proposal_id, status)["title"]
            except (InvalidProjectDocumentId, ProjectDocumentNotFound):
                proposal_id = None
        return {"schema": "apatch.studio.decision-basis.v1", "specification": {"id": spec_id, "title": document["title"]}, "requirement": {key: requirement[key] for key in ("id", "title", "statement", "state", "state_label")}, "proposal": ({"id": proposal_id, "title": proposal_title, "criterion": requirement.get("acceptance")} if proposal_id else None), "verification": requirement["verification"], "technical": requirement["technical"]}
