#!/usr/bin/env python3
"""Read-Only Queue Reporter — MVP (TASK-0008).

Lector MANUAL, READ-ONLY, SIN AUTORIDAD del bus de coordinación.

Qué hace (y SOLO esto):
  1. lee ``coordination/tasks/*.md`` del checkout local (solo lectura);
  2. extrae el front-matter (parser mínimo de stdlib; sin evaluación dinámica
     ni deserializadores inseguros);
  3. detecta la PRESENCIA de artefactos hermanos
     (worklogs/reports/reviews/candidates/decisions) por convención de nombre;
  4. clasifica cada tarea (tabla §6 del MVP, con F1–F4);
  5. imprime una cola a stdout, agrupada por accionabilidad;
  6. MARCA ambigüedades en vez de resolverlas.

Qué NO hace (techo no relajable — overrides todo):
  - NO escribe/crea/modifica ningún archivo del repo (output solo a stdout).
  - NO ejecuta acciones, NO decide ni interpreta autoridad.
  - NO usa red, NO lee ``.env``/secrets/auth, NO importa ``assistant_os``.
  - NO fija ``READY``/``HUMAN_DECISION``/``HANDOFF_TO_MSO``/``human_final``.
  - NO mueve estados, NO promueve candidatos, NO ejecuta prosa (``next_action``).

El ``exit code`` es informativo (0 = reporte emitido); NUNCA codifica autoridad.

Contrato de diseño: coordination/proposals/READ_ONLY_QUEUE_REPORTER_MVP.md
Scope-lock (TASK-0007): coordination/proposals/READ_ONLY_QUEUE_REPORTER_IMPLEMENTATION_AUTHORIZATION.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --- Contrato de estados (mirror de coordination/schemas/TASK.schema.md v3) ---
# Embebido como constante determinista; el schema es prosa Markdown y parsearlo
# introduciría no-determinismo. Mantener sincronizado con TASK.schema.md.
STATUS_ENUM = frozenset(
    {
        "DRAFT",
        "READY",
        "IN_PROGRESS",
        "EVIDENCE_READY",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
        "DECISION_PROPOSED",
        "HUMAN_DECISION",
        "HANDOFF_TO_MSO",
        "BLOCKED",
        "ABORTED",
        "CLOSED_REJECTED",
    }
)
TERMINAL_STATUSES = frozenset({"HANDOFF_TO_MSO", "CLOSED_REJECTED", "ABORTED"})

# Campos required del schema v3 (para reporte de ausencias y regla C2/F1).
REQUIRED_FIELDS = (
    "id",
    "title",
    "author",
    "authority",
    "assigned_agent",
    "reviewer",
    "status",
    "last_legit_status",
    "scope",
    "permissions",
    "risks",
    "evidence",
    "files_touched",
    "proposed_decision",
    "blocked",
    "next_action",
    "created_at",
    "updated_at",
)

# Directorios de artefactos hermanos: tipo -> subdirectorio en coordination/.
ARTIFACT_DIRS = {
    "worklog": "worklogs",
    "report": "reports",
    "review": "reviews",
    "candidate": "candidates",
    "decision": "decisions",
}

# --- Clasificaciones (enum del Reporter; distinto del enum `status`) ---
LEGACY_AMBIGUOUS = "LEGACY_AMBIGUOUS"
DRAFT_ACTIVE = "DRAFT_ACTIVE"
DRAFT_SUPERSEDED = "DRAFT_SUPERSEDED"
DRAFT_DESIGN_MERGED = "DRAFT_DESIGN_MERGED"
CLOSED_IN_COORDINATION_PLANE = "CLOSED_IN_COORDINATION_PLANE"
BLOCKED_OBS = "BLOCKED_OBS"
READY_FOR_EXECUTOR = "READY_FOR_EXECUTOR"
READY_FOR_REVIEWER = "READY_FOR_REVIEWER"
NO_OP_TERMINAL = "NO_OP_TERMINAL"
WAITING = "WAITING"

# --- Flags (marcas, no acciones) ---
FLAG_REQUIRES_HUMAN_INTERPRETATION = "REQUIRES_HUMAN_INTERPRETATION"
FLAG_MSO_ONLY_NEXT = "MSO_ONLY_NEXT"
FLAG_NO_AUTO_REVIEW = "NO_AUTO_REVIEW"

# --- role_destination ---
JORGE = "JORGE"
CLAUDE = "CLAUDE"
CODEX = "CODEX"
MSO = "MSO"
NONE = "NONE"

# Agrupación para el render (orden determinista de grupos).
GROUPS = (
    ("ACTIONABLE", (READY_FOR_EXECUTOR, READY_FOR_REVIEWER)),
    ("NEEDS HUMAN (Jorge)", (DRAFT_ACTIVE, DRAFT_SUPERSEDED, DRAFT_DESIGN_MERGED, BLOCKED_OBS)),
    ("WAITING", (WAITING,)),
    ("CLOSED / NO-OP", (CLOSED_IN_COORDINATION_PLANE, NO_OP_TERMINAL)),
    ("OBSERVATIONS", (LEGACY_AMBIGUOUS,)),
)


# --------------------------------------------------------------------------- #
# Front-matter parser (stdlib, anti-inyección: nunca evalúa ni ejecuta nada)
# --------------------------------------------------------------------------- #
def _scalar(raw: str):
    """Convierte un escalar YAML simple. Nunca evalúa: solo normaliza tipos."""
    v = raw.strip()
    if not v:
        return None
    if v[0] in ("'", '"'):
        quote = v[0]
        end = v.find(quote, 1)
        return v[1:end] if end != -1 else v[1:]
    # Comentario inline en valor sin comillas: ' #' en adelante se descarta.
    hashpos = v.find(" #")
    if hashpos != -1:
        v = v[:hashpos].strip()
    if v in ("null", "~", ""):
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def _parse_block(lines: list[str]):
    """Parser indentación-aware de un subconjunto de YAML (maps + secuencias).

    Soporta lo que aparece en el front-matter de las TASK: escalares, listas de
    bloque (``- item``) y mapas anidados. NUNCA ejecuta ni interpreta valores.
    """
    items: list[tuple[int, str]] = []
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        indent = len(ln) - len(ln.lstrip(" "))
        items.append((indent, ln.strip()))

    pos = 0

    def parse(level: int):
        nonlocal pos
        mapping: dict = {}
        sequence: list = []
        while pos < len(items):
            indent, content = items[pos]
            if indent < level:
                break
            if indent > level:
                # Indentación inesperada: ignorar de forma segura (fail-closed).
                pos += 1
                continue
            if content.startswith("- ") or content == "-":
                value = content[1:].strip()
                pos += 1
                if value == "":
                    sequence.append(parse(level + 1))
                else:
                    sequence.append(_scalar(value))
            else:
                key, sep, rest = content.partition(":")
                if not sep:
                    pos += 1
                    continue
                key = key.strip()
                rest = rest.strip()
                pos += 1
                if rest == "":
                    if pos < len(items) and items[pos][0] > level:
                        mapping[key] = parse(items[pos][0])
                    else:
                        mapping[key] = None
                else:
                    mapping[key] = _scalar(rest)
        if sequence and not mapping:
            return sequence
        return mapping

    result = parse(0)
    return result if isinstance(result, dict) else {}


def parse_frontmatter(text: str) -> Optional[dict]:
    """Extrae el front-matter YAML entre los delimitadores ``---``.

    Devuelve un dict de claves de nivel superior, o ``None`` si no hay
    front-matter delimitado (entrada inválida ⇒ el llamador hace fail-closed).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    return _parse_block(lines[1:end])


# --------------------------------------------------------------------------- #
# Detección de presencia / legacy (todo read-only, sin efectos)
# --------------------------------------------------------------------------- #
def task_number(name: str) -> Optional[str]:
    """Extrae el correlativo ``NNNN`` de un nombre/ID ``TASK-NNNN...``."""
    m = re.search(r"TASK-(\d{4})", name)
    return m.group(1) if m else None


def is_legacy(path: Path) -> bool:
    """``True`` si el archivo usa naming v1 (slug en el nombre, no solo NNNN)."""
    return re.fullmatch(r"TASK-\d{4}", path.stem) is None


def detect_presence(number: str, coord_root: Path) -> dict:
    """Presencia booleana de artefactos hermanos por convención de nombre.

    Solo comprueba EXISTENCIA (``TASK-NNNN*``) en cada subdirectorio; nunca lee
    ni interpreta el contenido de los artefactos.
    """
    pattern = re.compile(rf"TASK-{number}(\D|$)")
    present = {kind: False for kind in ARTIFACT_DIRS}
    for kind, dirname in ARTIFACT_DIRS.items():
        directory = coord_root / dirname
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            if entry.is_file() and pattern.match(entry.name):
                present[kind] = True
                break
    return present


def deliverables_present(fm: dict, repo_root: Path) -> bool:
    """¿Todos los entregables no-task declarados ya existen en el working tree?

    Compara SOLO presencia de los paths declarados en ``evidence``/
    ``files_touched`` que no sean archivos de tarea. Sin entregables declarados
    ⇒ ``False`` (se trata como DRAFT activo, no supersedido).
    """
    declared: list[str] = []
    for key in ("evidence", "files_touched"):
        value = fm.get(key)
        if isinstance(value, list):
            declared.extend(p for p in value if isinstance(p, str))
    non_task = [
        p for p in declared if not p.replace("\\", "/").startswith("coordination/tasks/")
    ]
    if not non_task:
        return False
    return all((repo_root / p).exists() for p in non_task)


# --------------------------------------------------------------------------- #
# Modelo de datos + clasificación
# --------------------------------------------------------------------------- #
@dataclass
class TaskRecord:
    id: str
    file: str
    number: Optional[str]
    status: Optional[str]
    last_legit_status: Optional[str]
    assigned_agent: Optional[str]
    reviewer: Optional[str]
    reviewer_delegate: Optional[str]
    blocked: object
    legacy: bool
    artifacts: dict
    missing_required: list
    deliverables_present: bool
    classification: str = BLOCKED_OBS
    role_destination: str = JORGE
    next_legal_action: Optional[str] = None
    flags: list = field(default_factory=list)
    notes: str = ""


def classify(rec: TaskRecord) -> None:
    """Aplica la tabla §6 (primer match gana; fail-closed por defecto).

    Muta ``rec`` fijando classification/role/next/flags/notes. No tiene otros
    efectos: no escribe, no ejecuta, no decide autoridad.
    """
    status = rec.status

    # C1 — status ausente o fuera de enum ⇒ marcar.
    if status is None or status not in STATUS_ENUM:
        rec.classification = BLOCKED_OBS
        rec.role_destination = JORGE
        rec.notes = "status ausente o fuera de enum"
        return

    # C2 (F1) — legacy / blocked-DRAFT / falta last_legit_status ⇒ degradar SOLO esta fila.
    if (
        rec.legacy
        or (status == "DRAFT" and rec.blocked is True)
        or ("last_legit_status" in rec.missing_required)
    ):
        rec.classification = LEGACY_AMBIGUOUS
        rec.role_destination = NONE
        notes = []
        if "last_legit_status" in rec.missing_required:
            notes.append("missing: last_legit_status")
        if rec.legacy:
            notes.append("legacy v1 naming, preserved")
        rec.notes = "; ".join(notes) or "legacy/ambiguo: observar, no avanzar"
        return

    # C3 — estados terminales ⇒ no-op.
    if status in TERMINAL_STATUSES:
        rec.classification = NO_OP_TERMINAL
        rec.role_destination = NONE
        rec.notes = f"terminal ({status})"
        return

    # C4 (F4) — HUMAN_DECISION ⇒ cerrado en el plano; siguiente paso SOLO MSO.
    if status == "HUMAN_DECISION":
        rec.classification = CLOSED_IN_COORDINATION_PLANE
        rec.role_destination = MSO
        rec.flags.append(FLAG_MSO_ONLY_NEXT)
        rec.next_legal_action = None
        rec.notes = "MSO out-of-plane; el Reporter no sugiere ninguna transicion"
        return

    # C5 — en curso ⇒ esperar.
    if status in ("IN_PROGRESS", "IN_REVIEW"):
        rec.classification = WAITING
        rec.role_destination = NONE
        rec.notes = f"en curso ({status})"
        return

    # C6 / C6b — EVIDENCE_READY.
    if status == "EVIDENCE_READY":
        if rec.reviewer is not None and rec.reviewer == rec.assigned_agent:
            rec.classification = BLOCKED_OBS
            rec.role_destination = JORGE
            rec.flags.append(FLAG_NO_AUTO_REVIEW)
            rec.notes = "reviewer == assigned_agent (no auto-review)"
            return
        if rec.artifacts.get("report") and rec.artifacts.get("worklog"):
            rec.classification = READY_FOR_REVIEWER
            rec.role_destination = CODEX
            rec.next_legal_action = "EVIDENCE_READY -> IN_REVIEW"
            return
        rec.classification = BLOCKED_OBS
        rec.role_destination = JORGE
        rec.notes = "EVIDENCE_READY sin report+worklog presentes (conflicto)"
        return

    # C7 — CHANGES_REQUESTED ⇒ vuelve al ejecutor.
    if status == "CHANGES_REQUESTED":
        rec.classification = READY_FOR_EXECUTOR
        rec.role_destination = CLAUDE
        rec.next_legal_action = "CHANGES_REQUESTED -> IN_PROGRESS"
        return

    # C8 — READY ⇒ ejecutor toma la tarea.
    if status == "READY":
        rec.classification = READY_FOR_EXECUTOR
        rec.role_destination = CLAUDE
        rec.next_legal_action = "READY -> IN_PROGRESS"
        return

    # C9 (F2) — DRAFT con entregables ya presentes ⇒ supersedido; NUNCA READY ciego.
    if status == "DRAFT":
        if rec.deliverables_present:
            rec.classification = DRAFT_SUPERSEDED
            rec.role_destination = JORGE
            rec.flags.append(FLAG_REQUIRES_HUMAN_INTERPRETATION)
            rec.next_legal_action = None
            rec.notes = (
                "entregables ya presentes; etiquetas candidatas: "
                "DRAFT_SUPERSEDED | DRAFT_DESIGN_MERGED (decide Jorge)"
            )
            return
        # C10 (F2b) — DRAFT sin entregables ⇒ candidato DRAFT->READY (acto de Jorge).
        rec.classification = DRAFT_ACTIVE
        rec.role_destination = JORGE
        rec.next_legal_action = "DRAFT -> READY (candidato; lo fija Jorge)"
        return

    # C11 / else — fail-closed.
    rec.classification = BLOCKED_OBS
    rec.role_destination = JORGE
    rec.notes = "fail-closed (no clasificable)"


# --------------------------------------------------------------------------- #
# Construcción de la cola + render
# --------------------------------------------------------------------------- #
def build_record(path: Path, coord_root: Path, repo_root: Path) -> TaskRecord:
    """Lee UNA tarea (read-only) y construye su ``TaskRecord`` ya clasificado.

    Cualquier fallo de lectura/parseo degrada SOLO esta fila (fail-closed); el
    barrido global continúa.
    """
    number = task_number(path.name)
    legacy = is_legacy(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    fm = parse_frontmatter(text) or {}

    raw_status = fm.get("status")
    status = raw_status if isinstance(raw_status, str) else None
    missing_required = [k for k in REQUIRED_FIELDS if k not in fm]

    rec = TaskRecord(
        id=fm.get("id") if isinstance(fm.get("id"), str) else (path.stem),
        file=str(path.name),
        number=number,
        status=status,
        last_legit_status=fm.get("last_legit_status")
        if isinstance(fm.get("last_legit_status"), str)
        else None,
        assigned_agent=fm.get("assigned_agent")
        if isinstance(fm.get("assigned_agent"), str)
        else None,
        reviewer=fm.get("reviewer") if isinstance(fm.get("reviewer"), str) else None,
        reviewer_delegate=fm.get("reviewer_delegate")
        if isinstance(fm.get("reviewer_delegate"), str)
        else None,
        blocked=fm.get("blocked"),
        legacy=legacy,
        artifacts=detect_presence(number, coord_root) if number else {k: False for k in ARTIFACT_DIRS},
        missing_required=missing_required,
        deliverables_present=deliverables_present(fm, repo_root),
    )
    classify(rec)
    return rec


def build_records(repo_root: Path) -> list[TaskRecord]:
    """Barre ``coordination/tasks/*.md`` de forma determinista (orden por nombre)."""
    coord_root = repo_root / "coordination"
    tasks_dir = coord_root / "tasks"
    if not tasks_dir.is_dir():
        raise FileNotFoundError(f"no existe el directorio de tareas: {tasks_dir}")
    files = sorted(p for p in tasks_dir.glob("*.md") if p.is_file())
    return [build_record(p, coord_root, repo_root) for p in files]


def _sort_key(rec: TaskRecord):
    return (rec.number or "9999", rec.id, rec.file)


def render(records: list[TaskRecord]) -> str:
    """Renderiza la cola a texto efímero, agrupado por accionabilidad.

    Output DESCRIPTIVO: no contiene órdenes aplicadas; las sugerencias son para
    que Jorge decida. Determinista para un mismo conjunto de archivos.
    """
    lines: list[str] = []
    lines.append("READ-ONLY QUEUE REPORTER -- local working tree snapshot")
    lines.append("(read-only; no muta nada; clasificacion, no autoridad)")
    lines.append("")

    by_class: dict[str, list[TaskRecord]] = {}
    for rec in records:
        by_class.setdefault(rec.classification, []).append(rec)

    for header, classes in GROUPS:
        bucket = []
        for cls in classes:
            bucket.extend(by_class.get(cls, []))
        bucket.sort(key=_sort_key)
        lines.append(header)
        if not bucket:
            lines.append("  (ninguna)")
        else:
            for rec in bucket:
                lines.append(_render_row(rec))
        lines.append("")

    lines.append(_render_summary(records))
    return "\n".join(lines)


def _render_row(rec: TaskRecord) -> str:
    tail_parts = []
    if rec.next_legal_action:
        tail_parts.append(f"next: {rec.next_legal_action}")
    if rec.flags:
        tail_parts.append("[" + ", ".join(rec.flags) + "]")
    if rec.notes:
        tail_parts.append(rec.notes)
    tail = "  ".join(tail_parts)
    task_id = rec.file[:-3] if rec.file.endswith(".md") else rec.file
    status = rec.status or "—"
    return f"  {task_id:<34} {status:<16} {rec.classification:<28} {tail}".rstrip()


def _render_summary(records: list[TaskRecord]) -> str:
    total = len(records)
    actionable = sum(
        1 for r in records if r.classification in (READY_FOR_EXECUTOR, READY_FOR_REVIEWER)
    )
    needs_human = sum(
        1
        for r in records
        if r.classification in (DRAFT_ACTIVE, DRAFT_SUPERSEDED, DRAFT_DESIGN_MERGED, BLOCKED_OBS)
    )
    waiting = sum(1 for r in records if r.classification == WAITING)
    closed = sum(
        1
        for r in records
        if r.classification in (CLOSED_IN_COORDINATION_PLANE, NO_OP_TERMINAL)
    )
    legacy = sum(1 for r in records if r.classification == LEGACY_AMBIGUOUS)
    return (
        f"summary: {total} tasks | {actionable} actionable | {needs_human} needs-human "
        f"| {waiting} waiting | {closed} closed/no-op | {legacy} legacy"
    )


def report(repo_root: Path) -> str:
    """Construye y renderiza la cola (función pura, sin efectos de escritura)."""
    return render(build_records(repo_root))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coordination_queue_reporter",
        description=(
            "Lector manual READ-ONLY de la cola de coordinacion. "
            "Lee coordination/tasks/*.md, clasifica y reporta a stdout. "
            "No escribe, no ejecuta, no decide autoridad."
        ),
        epilog="exit code informativo (0 = reporte emitido); nunca codifica autoridad.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="raiz del repo (que contiene coordination/). Por defecto: cwd.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    repo_root = Path(args.root).resolve() if args.root else Path.cwd()
    try:
        output = report(repo_root)
    except FileNotFoundError as exc:
        print(f"coordination_queue_reporter: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
