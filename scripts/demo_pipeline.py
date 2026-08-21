"""Drive the whole CurriculumOS pipeline over HTTP, end to end.

Same path the teacher workspace takes, in one run: upload -> extract
curriculum -> embed -> parse questions -> map -> emphasis -> teaching units
-> calendar -> plan -> disrupt -> replan. Generation is left to the UI
because it's the slow, per-lesson step.

    python scripts/demo_pipeline.py --syllabus path/to/syllabus.pdf \
        --paper "2024:final:path/to/final.pdf" \
        --paper "2022:mid1:path/to/mid1.pdf"

Every step prints what actually landed. Nothing here is a fixture: it
posts real files to a running server and reports the real counts back,
so a step that silently does nothing shows up as a zero rather than as a
green check.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "http://127.0.0.1:8000"


def _request(method: str, path: str, payload: Any = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            return json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {body}") from exc


def _upload(path: Path, title: str, doc_type: str) -> dict:
    """Multipart upload without a dependency — urllib has no multipart
    helper, and the body is small and fully known here.
    """
    boundary = "----curriculumosdemo"
    parts: list[bytes] = []
    for name, value in (("title", title), ("doc_type", doc_type)):
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
        )
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n".encode()
    )
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    req = urllib.request.Request(f"{BASE}/ingestion/documents", data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"upload {path.name} failed: {exc.read().decode(errors='replace')}") from exc


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 68}\n{n}. {title}\n{'=' * 68}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--syllabus", required=True, type=Path)
    ap.add_argument(
        "--paper",
        action="append",
        default=[],
        metavar="YEAR:REF:PATH",
        help="repeatable, e.g. --paper 2024:final:D:/DSA Final 2024.pdf",
    )
    ap.add_argument("--subject", default="Data Structures")
    ap.add_argument("--class-id", dest="class_id", default="CS-4A")
    ap.add_argument("--min-confidence", type=float, default=0.15)
    args = ap.parse_args()

    if _request("GET", "/health")["status"] != "ok":
        raise SystemExit("server is not healthy — start it with `uvicorn app.main:app`")

    step(1, "Upload and parse source documents")
    syllabus = _upload(args.syllabus, args.syllabus.stem, "syllabus")
    print(f"  syllabus  {syllabus['parser_used']:15} {syllabus['span_count']:4} spans  {syllabus['title']}")
    papers = []
    for spec in args.paper:
        year, ref, path = spec.split(":", 2)
        doc = _upload(Path(path), Path(path).stem, "past_paper")
        doc["_year"], doc["_ref"] = int(year), ref
        papers.append(doc)
        print(f"  paper     {doc['parser_used']:15} {doc['span_count']:4} spans  {doc['title']}")

    step(2, "Extract curriculum structure from the syllabus")
    nodes = _request("POST", f"/ingestion/documents/{syllabus['id']}/curriculum")
    edges = _request("GET", "/curriculum-edges")
    kinds: dict[str, int] = {}
    for n in nodes:
        kinds[n["node_type"]] = kinds.get(n["node_type"], 0) + 1
    print(f"  {len(nodes)} nodes {kinds}, {len(edges)} edges")
    print(f"  embedded: {_request('POST', '/ingestion/curriculum/embeddings')['nodes_embedded']}")

    step(3, "Parse exam questions")
    for doc in papers:
        report = _request(
            "POST",
            f"/ingestion/documents/{doc['id']}/questions",
            {"year": doc["_year"], "paper_ref": doc["_ref"]},
        )
        print(f"  {doc['title'][:40]:42} {report['questions_created']:3} questions")
    questions = _request("GET", "/questions")
    with_marks = sum(1 for q in questions if q["marks"] is not None)
    print(f"  total {len(questions)} questions, {with_marks} with a mark allocation")

    step(4, "Map questions to objectives (ensemble)")
    total = 0
    for q in questions:
        mapped = _request(
            "POST", f"/mappings/questions/{q['id']}", {"min_confidence": args.min_confidence}
        )
        total += len(mapped)
        print(f"  {q['question_ref']:18} {len(mapped):2} objective(s)")
    print(f"  {total} mappings total")

    step(5, "Historical assessment emphasis")
    emphasis = _request("GET", "/emphasis/")
    labels = {n["id"]: n["label"] for n in _request("GET", "/curriculum-nodes")}
    emphasis.sort(key=lambda r: -r["score"])
    for r in emphasis[:8]:
        print(f"  {r['score']:.3f}  {labels.get(r['node_id'], '?')[:58]}")

    step(6, "Teaching units")
    objectives = [n["id"] for n in _request("GET", "/curriculum-nodes") if n["node_type"] == "objective"]
    units = _request(
        "POST",
        "/ingestion/teaching-units",
        {
            "node_ids": objectives,
            "default_duration_minutes": 60,
            "priorities": {r["node_id"]: r["score"] for r in emphasis},
        },
    )
    print(f"  {len(units)} teaching units created, priority seeded from emphasis")

    step(7, "Academic calendar and timetable")
    start = dt.date.today().replace(day=1)
    end = start + dt.timedelta(days=90)
    calendar = _request(
        "POST",
        "/calendars/",
        {"school_id": "pilot-school", "term_start": start.isoformat(), "term_end": end.isoformat()},
    )
    print(f"  calendar {start} -> {end}, {calendar['day_count']} days modelled")
    windows = _request(
        "POST",
        f"/calendars/{calendar['id']}/instruction-windows",
        {
            "slots": [
                {
                    "subject": args.subject,
                    "class_id": args.class_id,
                    "weekday": wd,
                    "start_time": "09:00",
                    "end_time": "10:00",
                }
                for wd in (0, 2, 4)  # Mon / Wed / Fri
            ]
        },
    )
    print(f"  {windows['windows_created']} instruction windows (Mon/Wed/Fri 09:00-10:00)")

    step(8, "Solve the term plan")
    plan = _request(
        "POST",
        "/planning/plans",
        {
            "calendar_id": calendar["id"],
            "subject": args.subject,
            "class_id": args.class_id,
            "node_ids": objectives,
            "trigger_reason": "initial_plan",
        },
    )
    print(f"  solver: {plan['status']}")
    print(f"  {len(plan['assignments'])} units scheduled, {len(plan['unscheduled_unit_ids'])} unscheduled")
    scheduled = _request("GET", f"/planning/plans/{plan['plan_version_id']}")
    for row in scheduled[:6]:
        print(f"    {row['date']}  {row['node_label'][:52]}")

    step(9, "Disruption and replan")
    if not scheduled:
        print("  nothing scheduled — skipping")
        return 0
    closed = scheduled[0]["date"]
    disrupted = _request("POST", f"/calendars/{calendar['id']}/disrupt", {"date": closed, "reason": "school closed"})
    print(f"  school closed {closed}: {disrupted['windows_disrupted']} window(s) withdrawn")
    replan = _request(
        "POST",
        "/planning/plans",
        {
            "calendar_id": calendar["id"],
            "subject": args.subject,
            "class_id": args.class_id,
            "node_ids": objectives,
            "trigger_reason": "calendar_disruption",
            "parent_version_id": plan["plan_version_id"],
        },
    )
    print(f"  replan: {replan['status']}")
    print(f"  {replan['unchanged_count']} lessons unchanged, {replan['moved_count']} moved, "
          f"{len(replan['unscheduled_unit_ids'])} dropped")
    print("\n  A good replan is measured by how little it disturbs.")

    print(f"\nDone. Open {BASE} to walk the same flow in the workspace.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
