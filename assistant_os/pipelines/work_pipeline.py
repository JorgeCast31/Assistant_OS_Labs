"""
WORK Domain Pipeline v1

Entry point: execute(plan, context_id) -> DomainResult

Dispatches to the appropriate WORK execution helper based on plan action.
All patchable integration names are lazy-imported from
``integrations.work_gateway`` — the non-HTTP aggregation layer introduced in
M0.8.  Prior to M0.8 these were imported from ``webhook_server`` (HTTP layer).
Test patches should target ``assistant_os.integrations.work_gateway.*`` for
the pipeline execution path.
"""

from __future__ import annotations

from ..contracts import (
    DomainResult,
    make_domain_result,
    ACTION_WORK_QUERY,
    ACTION_WORK_CREATE,
    ACTION_WORK_CREATE_TEST,
    ACTION_WORK_UPDATE,
    ACTION_WORK_UPDATE_BULK,
    ACTION_WORK_DELETE,
    ACTION_WORK_DELETE_TEST,
    ACTION_WORK_TEST_RESET,
    RESULT_TYPE_WORK_QUERY,
    RESULT_TYPE_WORK_CREATE,
    RESULT_TYPE_WORK_UPDATE,
    RESULT_TYPE_WORK_UPDATE_PREVIEW,
    RESULT_TYPE_WORK_UPDATE_BULK,
    RESULT_TYPE_WORK_DELETE,
    OP_WORK_UPDATE,
    EXECUTION_STATUS_REAL,
)


def execute(plan: dict, context_id: str) -> DomainResult:
    """
    Dispatch a WORK domain plan to the appropriate execution helper.

    Args:
        plan:       ExecutionPlan with action, filters, and metadata.
        context_id: Canonical context ID for this request.

    Returns:
        DomainResult — no transport wrapping.
    """
    result = _dispatch(plan, context_id)
    result["execution_status"] = EXECUTION_STATUS_REAL
    return result


def _dispatch(plan: dict, context_id: str) -> DomainResult:
    action = plan.get("action", "")

    if action == ACTION_WORK_QUERY:
        return _work_query_execute(plan, context_id)

    if action in (ACTION_WORK_CREATE, ACTION_WORK_CREATE_TEST):
        return _work_create_execute(plan, context_id)

    if action in (ACTION_WORK_DELETE, ACTION_WORK_DELETE_TEST, ACTION_WORK_TEST_RESET):
        return _work_delete_execute(plan, context_id)

    if action == ACTION_WORK_UPDATE:
        # Phase 2 (confirmed update): filters contain notion_page_id resolved in Phase 1.
        # Phase 1 (preview): no notion_page_id yet — resolve target and return proposal.
        if plan.get("filters", {}).get("notion_page_id"):
            return _work_update_execute(plan, context_id)
        text = plan.get("raw_text", "")
        return _work_update_preview_execute(plan, context_id, text)

    if action == ACTION_WORK_UPDATE_BULK:
        return _work_update_bulk_execute(plan, context_id)

    # Unknown WORK action — return a safe no-op result.
    return make_domain_result(
        ok=False,
        result_type="work_unknown",
        domain="WORK",
        message=f"Acción WORK desconocida: {action}",
        data={"plan": dict(plan)},
        error={"type": "UnknownAction", "message": f"No handler for WORK action: {action}"},
    )


# ---------------------------------------------------------------------------
# Execution helpers
# All patchable integration names are lazy-imported from work_gateway so
# that test patches applied to assistant_os.integrations.work_gateway.* fire.
# ---------------------------------------------------------------------------


def _work_query_execute(plan: dict, context_id: str) -> DomainResult:
    """Execute a WORK query and return DomainResult (no transport wrapping)."""
    from ..integrations.work_gateway import (
        check_notion_available,
        get_notion_status,
        format_work_query_response,
    )
    from ..tools.notion.query_database_tool import QueryDatabaseTool

    filters = plan.get("filters", {})

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    tool_result = QueryDatabaseTool().execute({"filters": filters, "limit": 20})

    if not tool_result.ok:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_QUERY,
            domain="WORK",
            message="Error consultando la base de datos.",
            data={"plan": dict(plan)},
            error={
                "type": tool_result.error.code,
                "message": tool_result.error.message,
            },
        )

    items = tool_result.data.get("items", [])
    total = tool_result.data.get("total", 0)
    formatted = format_work_query_response({"ok": True, "items": items, "total": total})

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_WORK_QUERY,
        domain="WORK",
        message=f"Se encontraron {total} tarea(s)." if total > 0 else "No se encontraron tareas.",
        data={
            "type": "work_query",
            "items": items,
            "total": total,
            "formatted": formatted,
            "filters": filters,
            "plan": dict(plan),
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


def _work_update_preview_execute(plan: dict, context_id: str, text: str) -> DomainResult:
    """
    Execute WORK_UPDATE Phase 1 and return DomainResult (no transport wrapping).

    Resolves the target item using project-first resolution, reads current
    values, and returns a proposal DomainResult with valid options.

    When plan.filters["bulk"] is True (e.g. "marca todas las tareas de X como Y"):
    - Queries Notion by filter_project / filter_status (not keywords)
    - Raises limit to 50
    - Applies safety rules: N > 10 → RISK_HIGH; N > 50 → reject
    - Pre-populates selected_notion_page_ids so the user just confirms
    - Preview lists the affected task titles
    """
    from ..integrations.work_gateway import (
        check_notion_available,
        get_notion_status,
        get_editable_field_options,
        search_work_items_with_filters,
        search_work_items_by_title,
        get_work_item_by_id,
        store_pending_plan,
        generate_update_preview,
        query_work_db,
    )
    # ACTION_WORK_UPDATE_BULK is already imported at module top-level from contracts.
    # No lazy-import needed — it is a constant, not a patchable integration call.

    filters = plan.get("filters", {})
    changes = filters.get("changes", [])
    keywords = filters.get("keywords", [])
    is_bulk = filters.get("bulk", False)

    hint_project = filters.get("hint_project") or filters.get("filter_project")
    hint_domain = filters.get("hint_domain")
    hint_status = filters.get("hint_status") or filters.get("filter_status")

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    options_result = get_editable_field_options()
    editable_options = options_result if options_result.get("ok") else {"options": {"domain": [], "project": [], "status": []}}
    real_options = editable_options.get("options", {})

    # ------------------------------------------------------------------
    # BULK PATH: "marca todas las tareas de X como Y"
    # Query by structured filters, no keyword search, pre-select all IDs.
    # ------------------------------------------------------------------
    if is_bulk:
        # Fuzzy-match project name against real Notion options.
        # Uses accent-insensitive comparison so "consultoria" matches "Consultoría".
        import unicodedata

        def _fold(s: str) -> str:
            """Lowercase + strip accents for accent-insensitive comparison."""
            return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii").lower()

        resolved_project: str | None = None
        if hint_project:
            hint_folded = _fold(hint_project)
            for p in real_options.get("project", []):
                p_folded = _fold(p)
                if hint_folded in p_folded or p_folded in hint_folded:
                    resolved_project = p   # use the canonical Notion spelling
                    break
            # If no Notion option matched, resolved_project stays None → no filter applied
            # rather than passing an unrecognised value that Notion would ignore silently.

        resolved_status: str | None = None
        if hint_status:
            for s in real_options.get("status", []):
                if hint_status.upper() == s.upper():
                    resolved_status = s
                    break

        bulk_query_filters: dict = {}
        if resolved_project:
            bulk_query_filters["project"] = resolved_project
        if resolved_status:
            bulk_query_filters["status"] = resolved_status

        bulk_result = query_work_db(filters=bulk_query_filters, limit=50)
        if not bulk_result.get("ok"):
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
                domain="WORK",
                message="Error buscando tareas en Notion.",
                data={"plan": dict(plan)},
                error={"type": "SearchError", "message": bulk_result.get("error", "Error buscando ítems")},
            )

        bulk_matches = bulk_result.get("items", [])
        match_count = len(bulk_matches)

        # Safety: too many matches → reject
        if match_count > 50:
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
                domain="WORK",
                message=f"Demasiadas tareas ({match_count}). Añade filtros más específicos.",
                data={"plan": dict(plan)},
                error={"type": "TooManyMatches", "message": f"{match_count} tasks matched — add more filters"},
            )

        if match_count == 0:
            return make_domain_result(
                ok=True,
                result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
                domain="WORK",
                message="No se encontraron tareas que coincidan con los filtros.",
                data={
                    "type": "work_update_proposal",
                    "context_id": context_id,
                    "resolved": False,
                    "reason": "no_match",
                    "match_count": 0,
                    "matches": [],
                    "requires_confirmation": False,
                    "plan": dict(plan),
                },
                trace_id=plan.get("trace_id"),
                plan_id=plan.get("plan_id"),
            )

        # Safety: high risk if many matches
        bulk_risk = "RISK_HIGH" if match_count > 10 else "RISK_MEDIUM"

        enriched_bulk = [
            {
                "notion_page_id": m.get("notion_page_id"),
                "title": m.get("title"),
                "project": m.get("project"),
                "status": m.get("status"),
            }
            for m in bulk_matches
        ]

        # Build task-list preview (first 10 titles)
        title_list = "\n".join(
            f"  • {m.get('title', '(sin título)')}"
            for m in enriched_bulk[:10]
        )
        more = f"\n  … y {match_count - 10} más" if match_count > 10 else ""
        changes_desc = ", ".join(
            f"{c['field']} → {c['new_value']}"
            for c in changes
            if isinstance(c, dict) and c.get("field")
        ) or "sin cambios detectados"
        preview_text = (
            f"Actualizar {match_count} tareas ({changes_desc}):\n{title_list}{more}"
        )

        synced_plan = dict(plan)
        synced_plan["action"] = ACTION_WORK_UPDATE_BULK
        synced_plan["requires_confirmation"] = True
        synced_plan["risk_level"] = bulk_risk
        synced_plan["matches"] = enriched_bulk
        # Pre-select ALL matches — user just confirms
        synced_plan["selected_notion_page_ids"] = [
            m["notion_page_id"] for m in enriched_bulk if m.get("notion_page_id")
        ]
        # Flatten changes into the applied_changes dict expected by _work_update_bulk_execute
        synced_plan["applied_changes"] = {
            c["field"]: c["new_value"]
            for c in changes
            if isinstance(c, dict) and c.get("field")
        }
        synced_plan["editable_fields"] = list(synced_plan["applied_changes"].keys())

        store_pending_plan(
            context_id=context_id,
            plan=synced_plan,
            operation=OP_WORK_UPDATE,
            raw_text=text,
        )

        warning_msg = (
            f"⚠️ Riesgo alto: se afectarán {match_count} tareas."
            if match_count > 10 else ""
        )
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message=f"Se encontraron {match_count} tareas. Confirma para aplicar: {changes_desc}.",
            data={
                "type": "work_update_bulk_proposal",
                "context_id": context_id,
                "resolved": True,
                "total": match_count,
                "match_count": match_count,
                "preview": preview_text,
                "warning": warning_msg,
                "matches": enriched_bulk,
                "applied_changes": synced_plan["applied_changes"],
                "editable_fields": synced_plan["editable_fields"],
                "options": editable_options,
                "requires_confirmation": True,
                "risk_level": bulk_risk,
                "plan": synced_plan,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    # ------------------------------------------------------------------
    # SINGLE-TASK PATH (existing behaviour, unchanged)
    # ------------------------------------------------------------------
    import unicodedata as _ud

    def _fold_st(s: str) -> str:
        return _ud.normalize("NFD", s).encode("ascii", "ignore").decode("ascii").lower()

    valid_projects_folded = [_fold_st(p) for p in real_options.get("project", [])]
    if hint_project and _fold_st(hint_project) not in valid_projects_folded:
        hint_folded = _fold_st(hint_project)
        matched_project = None
        for p in real_options.get("project", []):
            if hint_folded in _fold_st(p) or _fold_st(p) in hint_folded:
                matched_project = p
                break
        hint_project = matched_project

    valid_domains = [d.lower() for d in real_options.get("domain", [])]
    if hint_domain and hint_domain.lower() not in valid_domains:
        hint_domain = None

    valid_statuses = [s.lower() for s in real_options.get("status", [])]
    if hint_status and hint_status.lower() not in valid_statuses:
        hint_status = None

    search_keywords = keywords if keywords else None
    if search_keywords and hint_project:
        keywords_lower = [kw.lower() for kw in search_keywords]
        if hint_project.lower() in keywords_lower:
            search_keywords = None

    search_result = search_work_items_with_filters(
        keywords=search_keywords,
        project=hint_project,
        domain=hint_domain,
        status=hint_status,
        limit=5,
    )

    if not search_result.get("ok"):
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="Error buscando tareas en Notion.",
            data={"plan": dict(plan)},
            error={"type": "SearchError", "message": search_result.get("error", "Error buscando ítems")},
        )

    matches = search_result.get("items", [])

    if len(matches) == 0 and hint_project:
        search_result = search_work_items_with_filters(
            keywords=search_keywords,
            project=hint_project,
            limit=5,
        )
        if search_result.get("ok"):
            matches = search_result.get("items", [])

    if len(matches) == 0 and search_keywords:
        search_result = search_work_items_by_title(search_keywords, limit=5)
        if search_result.get("ok"):
            matches = search_result.get("items", [])

    # ------------------------------------------------------------------
    # DOMINANT MATCH SCORING
    # When N > 1 results are returned, score each by keyword overlap.
    # If one match clearly outscores all others (≥ 2× the next best),
    # resolve as a single-task update instead of escalating to bulk.
    # ------------------------------------------------------------------
    if len(matches) > 1 and keywords:
        def _score_dm(title: str) -> int:
            t = _fold_st(title)
            score = 0
            for kw in keywords:
                k = _fold_st(kw)
                if k in t:
                    # Prefix match scores higher than substring match
                    score += 3 if t.startswith(k) else 2
                    # Longer keyword = more specific = higher confidence
                    score += len(k)
            return score

        scored = [(m, _score_dm(m.get("title", ""))) for m in matches]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_match, best_score = scored[0]
        second_score = scored[1][1] if len(scored) > 1 else 0

        # Dominant: best score is positive AND at least 2× the next candidate
        if best_score > 0 and (second_score == 0 or best_score >= 2 * second_score):
            matches = [best_match]

    if len(matches) == 0:
        synced_plan = dict(plan)
        synced_plan["requires_confirmation"] = False
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message="No se encontró ninguna tarea que coincida con la búsqueda.",
            data={
                "type": "work_update_proposal",
                "context_id": context_id,
                "resolved": False,
                "reason": "no_match",
                "match_count": 0,
                "matches": [],
                "search_context": {
                    "keywords": keywords,
                    "hint_project": hint_project,
                    "hint_domain": hint_domain,
                    "hint_status": hint_status,
                },
                "editable_fields": ["domain", "project", "status"],
                "options": editable_options,
                "requires_confirmation": False,
                "plan": synced_plan,
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    elif len(matches) == 1:
        item = matches[0]
        page_id = item.get("notion_page_id")
        full_item_result = None
        if page_id is not None:
            full_item_result = get_work_item_by_id(page_id)

        if not full_item_result.get("ok"):
            return make_domain_result(
                ok=False,
                result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
                domain="WORK",
                message="Error leyendo los detalles de la tarea.",
                data={"plan": dict(plan)},
                error={"type": "ItemReadError", "message": full_item_result.get("error", "Error leyendo ítem")},
            )

        full_item = full_item_result.get("item", {})
        preview_text = ""
        if full_item and isinstance(full_item, dict):
            preview_text = generate_update_preview(changes, full_item.get("title", ""))

        current_values = {}
        if full_item and isinstance(full_item, dict):
            current_values = {
                "domain": full_item.get("domain"),
                "project": full_item.get("project"),
                "status": full_item.get("status"),
            }

        synced_plan = dict(plan)
        synced_plan["requires_confirmation"] = True
        synced_plan["filters"] = {
            "notion_page_id": page_id,
            "current_values": current_values,
            "proposed_changes": changes,
            "title": "",
        }
        if full_item and isinstance(full_item, dict):
            synced_plan["filters"]["title"] = full_item.get("title", "")

        proposal_output = {
            "type": "work_update_proposal",
            "context_id": context_id,
            "resolved": True,
            "risk_level": "RISK_LOW",
            "match_count": 1,
            "notion_page_id": page_id,
            "title": "",
            "current_values": current_values,
            "proposed_changes": changes,
            "preview": preview_text,
            "editable_fields": ["domain", "project", "status"],
            "options": editable_options,
            "requires_confirmation": True,
            "plan": synced_plan,
        }
        if full_item and isinstance(full_item, dict):
            proposal_output["title"] = full_item.get("title", "")

        store_pending_plan(
            context_id=context_id,
            plan=synced_plan,
            operation=OP_WORK_UPDATE,
            raw_text=text,
        )

        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message=proposal_output.get("preview") or "Tarea encontrada y lista para actualizar.",
            data=proposal_output,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    else:
        enriched_matches = [
            {
                "notion_page_id": m.get("notion_page_id"),
                "title": m.get("title"),
                "domain": m.get("domain"),
                "project": m.get("project"),
                "status": m.get("status"),
            }
            for m in matches
        ]
        candidate_objs = [
            {"title": m.get("title"), "status": m.get("status")}
            for m in matches
        ]
        preview_text = generate_update_preview(changes, "") if changes else f"Actualizar {len(matches)} tareas"

        synced_plan = dict(plan)
        synced_plan["action"] = ACTION_WORK_UPDATE_BULK
        synced_plan["requires_confirmation"] = True
        synced_plan["matches"] = enriched_matches
        synced_plan["selected_notion_page_ids"] = []
        synced_plan["applied_changes"] = {}
        if "filters" in synced_plan:
            synced_plan["filters"] = dict(synced_plan["filters"])
            synced_plan["filters"]["ambiguous"] = True

        store_pending_plan(
            context_id=context_id,
            plan=synced_plan,
            operation=OP_WORK_UPDATE,
            raw_text=text,
        )

        bulk_proposal_data = {
            "type": "work_update_bulk_proposal",
            "context_id": context_id,
            "resolved": False,
            "total": len(matches),
            "match_count": len(matches),
            "preview": preview_text,
            "candidates": candidate_objs,
            "matches": enriched_matches,
            "message": f"Se encontraron {len(matches)} tareas. Selecciona cuáles quieres actualizar.",
            "editable_fields": ["domain", "project", "status"],
            "options": editable_options,
            "requires_confirmation": True,
            "plan": synced_plan,
        }
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_UPDATE_PREVIEW,
            domain="WORK",
            message=f"Se encontraron {len(matches)} tareas. Selecciona cuáles quieres actualizar.",
            data=bulk_proposal_data,
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )


def _work_update_bulk_execute(plan: dict, context_id: str) -> DomainResult:
    """
    Execute bulk WORK_UPDATE from a confirmed bulk proposal.

    Returns DomainResult (no transport wrapping).
    """
    from ..integrations.work_gateway import get_editable_field_options, update_work_item

    matches = plan.get("matches", [])
    selected_ids = plan.get("selected_notion_page_ids", [])
    applied_changes = plan.get("applied_changes", {})
    editable_fields = plan.get("editable_fields", ["domain", "project", "status"])

    options_result = get_editable_field_options()
    real_options = options_result.get("options", {}) if options_result.get("ok") else {}

    updated_items: list = []
    failed_items: list = []
    skipped_items: list = []

    valid_ids = {m["notion_page_id"] for m in matches}
    for page_id in selected_ids:
        if page_id not in valid_ids:
            skipped_items.append(page_id)
            continue

        changes_dict: dict = {}
        for field in editable_fields:
            if field in applied_changes:
                value = applied_changes[field]
                valid_values = real_options.get(field, [])
                if valid_values and value not in valid_values:
                    failed_items.append({
                        "notion_page_id": page_id,
                        "field": field,
                        "value": value,
                        "reason": "Valor no válido",
                        "error": None,
                    })
                    continue
                changes_dict[field] = value

        if not changes_dict:
            skipped_items.append(page_id)
            continue

        update_result = update_work_item(page_id=page_id, changes=changes_dict, current_values={})
        if update_result["ok"]:
            updated_items.append({"notion_page_id": page_id, "changes_applied": changes_dict})
        else:
            failed_items.append({
                "notion_page_id": page_id,
                "field": None,
                "value": None,
                "reason": None,
                "error": update_result.get("error") or "",
            })

    bulk_message = (
        f"Bulk update finalizado: {len(updated_items)} actualizados, "
        f"{len(failed_items)} fallidos, {len(skipped_items)} omitidos."
    )
    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_WORK_UPDATE_BULK,
        domain="WORK",
        message=bulk_message,
        data={
            "type": "work_update_bulk_result",
            "updated_count": len(updated_items),
            "updated_items": updated_items,
            "failed_items": failed_items,
            "skipped_items": skipped_items,
            "plan": dict(plan),
        },
    )


def _work_create_execute(plan: dict, context_id: str) -> DomainResult:
    """
    Execute WORK_CREATE from a confirmed plan and return DomainResult.

    Builds a WorkCreateRequest from plan filters, calls CreatePageTool,
    and returns a DomainResult. No transport wrapping.
    """
    from ..integrations.work_gateway import check_notion_available, get_notion_status
    from ..tools.notion.create_page_tool import CreatePageTool

    filters = plan.get("filters", {})
    title = filters.get("title", "").strip()

    if not title:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="No se puede crear la tarea: falta el título.",
            data={"plan": dict(plan)},
            error={"type": "ValidationError", "message": "Title is required"},
        )

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    work_request: dict = {"title": title}
    for field in ("project", "status", "load", "due", "notes"):
        if filters.get(field):
            work_request[field] = filters[field]

    tool_result = CreatePageTool().execute({"work_request": work_request})

    if tool_result.ok:
        created_title = tool_result.data.get("title", title)
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message=f"Tarea creada: {created_title}",
            data={
                "type": "work_create",
                "page_id": tool_result.data.get("page_id", ""),
                "url": tool_result.data.get("url", ""),
                "title": created_title,
                "plan": dict(plan),
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )
    else:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_CREATE,
            domain="WORK",
            message="No se pudo crear la tarea en Notion.",
            data={"plan": dict(plan)},
            error={
                "type": "WorkCreateError",
                "message": tool_result.error.message if tool_result.error else "Failed to create task in Notion",
            },
        )


def _work_delete_execute(plan: dict, context_id: str) -> DomainResult:
    """
    Execute WORK_DELETE / WORK_DELETE_TEST / WORK_TEST_RESET from a confirmed plan.

    Queries Notion for matching tasks, optionally filters by keyword, and archives
    the matched pages. Returns DomainResult. No transport wrapping.

    plan["filters"]["delete_all"] controls whether all tasks are deleted.
    plan["filters"]["keywords"]   controls keyword-based filtering when not delete_all.
    """
    from ..integrations.work_gateway import check_notion_available, get_notion_status, query_work_db
    from ..integrations.notion import archive_pages

    filters = plan.get("filters", {})
    keywords = filters.get("keywords", [])
    delete_all = filters.get("delete_all", False)

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    # Build Notion-side query filters from structured filter_project / filter_status.
    # This replaces the old "fetch all + in-memory keyword filter" approach for bulk-delete.
    notion_filters: dict = {}
    filter_project = filters.get("filter_project")
    filter_status = filters.get("filter_status")
    if filter_project:
        notion_filters["project"] = filter_project
    if filter_status:
        notion_filters["status"] = filter_status

    result = query_work_db(filters=notion_filters, limit=100)
    items = result.get("items", [])

    if not delete_all and keywords:
        keyword_lower = [k.lower() for k in keywords]
        items = [
            item for item in items
            if any(kw in (item.get("title") or "").lower() for kw in keyword_lower)
        ]
    elif not delete_all and not keywords and not filter_project and not filter_status:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="No se especificaron criterios de eliminación.",
            data={"plan": dict(plan)},
            error={
                "type": "ValidationError",
                "message": "No delete criteria specified. Use keywords or delete_all.",
            },
        )

    if not items:
        return make_domain_result(
            ok=True,
            result_type=RESULT_TYPE_WORK_DELETE,
            domain="WORK",
            message="No se encontraron tareas que coincidan con los criterios.",
            data={
                "type": "work_delete",
                "deleted_count": 0,
                "total_matched": 0,
                "plan": dict(plan),
            },
            trace_id=plan.get("trace_id"),
            plan_id=plan.get("plan_id"),
        )

    page_ids = [
        item["notion_page_id"]
        for item in items
        if item and isinstance(item, dict) and item.get("notion_page_id") is not None
    ]

    archived_count = archive_pages(page_ids)

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_WORK_DELETE,
        domain="WORK",
        message=f"Tareas eliminadas: {archived_count}/{len(page_ids)}",
        data={
            "type": "work_delete",
            "deleted_count": archived_count,
            "total_matched": len(page_ids),
            "plan": dict(plan),
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )


def _work_update_execute(plan: dict, context_id: str) -> DomainResult:
    """
    Execute WORK_UPDATE Phase 2 (confirmed single update) and return DomainResult.

    Validates proposed_changes against real Notion options and applies changes
    to the target page via UpdatePageTool. No transport wrapping.
    """
    from ..integrations.work_gateway import (
        check_notion_available, get_notion_status, get_editable_field_options, update_work_item
    )

    filters = plan.get("filters", {})
    page_id = filters.get("notion_page_id")
    current_values = filters.get("current_values", {})
    proposed_changes = filters.get("proposed_changes", [])
    title = filters.get("title", "")

    if not page_id:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE,
            domain="WORK",
            message="No se puede ejecutar la actualización: falta notion_page_id.",
            data={"plan": dict(plan)},
            error={
                "type": "ValidationError",
                "message": "Cannot execute update: notion_page_id missing",
            },
        )

    if not check_notion_available():
        notion_status = get_notion_status()
        error_msg = notion_status.get("last_error", {}).get("message", "Notion not configured")
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE,
            domain="WORK",
            message="Notion no está disponible.",
            data={"plan": dict(plan)},
            error={"type": "NotionUnavailable", "message": error_msg},
        )

    options_result = get_editable_field_options()
    real_options = options_result.get("options", {}) if options_result.get("ok") else {}

    ALLOWED_FIELDS = {"domain", "project", "status"}
    changes_dict: dict[str, str] = {}
    validation_warnings: list[str] = []

    for change in proposed_changes:
        field = change.get("field")
        new_value = change.get("new_value")

        if not field or not new_value:
            continue

        if field not in ALLOWED_FIELDS:
            validation_warnings.append(f"Campo '{field}' no permitido. Solo: {', '.join(ALLOWED_FIELDS)}")
            continue

        valid_values = real_options.get(field, [])
        if valid_values:
            valid_values_lower = [v.lower() for v in valid_values]
            if new_value.lower() not in valid_values_lower:
                matched = None
                for real_val in valid_values:
                    if new_value.lower() in real_val.lower() or real_val.lower() in new_value.lower():
                        matched = real_val
                        break
                if matched:
                    new_value = matched
                else:
                    validation_warnings.append(
                        f"Valor '{new_value}' no válido para {field}. Opciones: {', '.join(valid_values[:5])}"
                    )
                    continue
            else:
                idx = valid_values_lower.index(new_value.lower())
                new_value = valid_values[idx]

        changes_dict[field] = new_value

    if not changes_dict:
        error_msg = "No valid changes to apply"
        if validation_warnings:
            error_msg = f"No valid changes: {'; '.join(validation_warnings)}"
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE,
            domain="WORK",
            message="No se encontraron cambios válidos para aplicar.",
            data={"plan": dict(plan), "validation_warnings": validation_warnings},
            error={"type": "ValidationError", "message": error_msg},
        )

    update_result = update_work_item(page_id=page_id, changes=changes_dict, current_values=current_values)

    if not update_result["ok"]:
        return make_domain_result(
            ok=False,
            result_type=RESULT_TYPE_WORK_UPDATE,
            domain="WORK",
            message="No se pudo actualizar la tarea en Notion.",
            data={"plan": dict(plan)},
            error={
                "type": "NotionUpdateError",
                "message": update_result.get("error") or "Failed to update task in Notion",
            },
        )

    return make_domain_result(
        ok=True,
        result_type=RESULT_TYPE_WORK_UPDATE,
        domain="WORK",
        message="Tarea actualizada correctamente.",
        data={
            "type": "work_update_result",
            "updated": True,
            "notion_page_id": page_id,
            "title": title,
            "changes_applied": update_result.get("changes_applied", []),
            "plan": dict(plan),
        },
        trace_id=plan.get("trace_id"),
        plan_id=plan.get("plan_id"),
    )
