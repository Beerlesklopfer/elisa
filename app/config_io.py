"""
JSON-Austausch je TYP (nicht je Datensatz, nicht alles gebündelt).

Ein JSON enthält ALLE Datensätze EINES Typs (z. B. alle MCP-Tokens) unter
`items`, mit Typ-Header zur Validierung (`_header.type = elisa-<typ>`).
Referenzen über natürliche Schlüssel (Customer.number, Project.key), damit der
Austausch zwischen Systemen (Dev → Live) funktioniert. Import aktualisiert
bestehende Datensätze über ihren Schlüssel (update_or_create).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model

from app.models import (
    Customer, Project, MCPToken, LLMRoleDescription, EmailSettings, WorkerBackend,
    WorkItem,
)

User = get_user_model()

SCHEMA_VERSION = 1
TYPE_PREFIX = "elisa-"

_CUSTOMER_FIELDS = [
    "number", "name", "legal_form", "address_line1", "address_line2",
    "postal_code", "city", "region", "country", "vat_id", "registration_no",
    "contact_person", "contact_email", "phone", "website", "language", "notes",
]
_EMAIL_FIELDS = [
    "label", "host", "port", "username", "password", "use_tls", "use_ssl",
    "from_email", "timeout", "active",
]

# Registry je Typ: Modell, Felder, natürlicher Schlüssel, FK-Auflösung.
SPEC = {
    "customer": {"model": Customer, "fields": _CUSTOMER_FIELDS, "key": "number", "fks": {}},
    "project": {"model": Project, "fields": ["key", "name", "description", "archived"],
                "key": "key", "fks": {"customer": (Customer, "number")}},
    "mcptoken": {"model": MCPToken,
                 "fields": ["name", "token", "scope", "access", "active"],
                 "key": "token", "fks": {"project": (Project, "key")}},
    "llmrole": {"model": LLMRoleDescription,
                "fields": ["role", "iec_reference", "description"],
                "key": "role", "fks": {}},
    "emailsettings": {"model": EmailSettings, "fields": _EMAIL_FIELDS,
                      "key": "label", "fks": {}},
    "workerbackend": {"model": WorkerBackend,
                      "fields": ["name", "provider", "model", "base_url",
                                 "api_key", "mcp_base", "active"],
                      "key": "name", "fks": {"token": (MCPToken, "token")}},
    # WorkItem: Schlüssel (project, identifier); Selbst-M2M derived_from über
    # identifier; nullbare User-FKs (optional, falls Benutzer im Ziel fehlt).
    "workitem": {"model": WorkItem,
                 "fields": ["phase", "identifier", "title", "body", "rationale",
                            "status", "version", "generated_by_llm", "llm_model"],
                 "key": "identifier", "scope_fk": "project",
                 "fks": {"project": (Project, "key"),
                         "created_by": (User, "username", "optional"),
                         "approved_by": (User, "username", "optional")},
                 "m2m": {"derived_from": "identifier"}},
}
_MODEL_TO_TYPE = {spec["model"]: name for name, spec in SPEC.items()}


class ConfigImportError(ValueError):
    """Ungültiges/fremdes JSON (Header-/Typ-Validierung fehlgeschlagen)."""


def type_for(model) -> str:
    return _MODEL_TO_TYPE[model]


def _serialize(obj) -> dict:
    spec = SPEC[_MODEL_TO_TYPE[type(obj)]]
    data = {f: getattr(obj, f) for f in spec["fields"]}
    for fk_field, fk_def in spec["fks"].items():
        fk_key = fk_def[1]
        ref = getattr(obj, fk_field, None)
        data[fk_field] = getattr(ref, fk_key) if ref else None
    for m2m_field, rel_key in spec.get("m2m", {}).items():
        data[m2m_field] = [getattr(r, rel_key) for r in getattr(obj, m2m_field).all()]
    return data


def _header(model, **extra) -> dict:
    from django.utils import timezone
    tname = _MODEL_TO_TYPE[model]
    h = {
        "type": f"{TYPE_PREFIX}{tname}",
        "schema_version": SCHEMA_VERSION,
        "exported_at": timezone.now().isoformat(),
    }
    h.update(extra)
    return h


def export_type(model) -> dict:
    """Exportiert ALLE Datensätze eines Typs als ein JSON-Dict (Liste `items`)."""
    return {
        "_header": _header(model, count=model.objects.count()),
        "items": [_serialize(o) for o in model.objects.all()],
    }


def export_obj(obj) -> dict:
    """Exportiert GENAU EINEN Datensatz (Einzel-Export, Feld `item`)."""
    return {"_header": _header(type(obj)), "item": _serialize(obj)}


def _validate_header(model, payload: dict) -> None:
    expected = f"{TYPE_PREFIX}{_MODEL_TO_TYPE[model]}"
    hdr = (payload or {}).get("_header") or {}
    if hdr.get("type") != expected:
        raise ConfigImportError(
            f"Falscher Typ: erwartet '{expected}', gefunden '{hdr.get('type')}'.")
    if hdr.get("schema_version") not in (None, SCHEMA_VERSION):
        raise ConfigImportError(
            f"Inkompatible Schema-Version {hdr.get('schema_version')}.")


def _import_one(model, data: dict):
    """Importiert/aktualisiert EINEN Datensatz. Liefert (obj, created, m2m_pending)."""
    spec = SPEC[_MODEL_TO_TYPE[model]]
    data = dict(data)
    # M2M (z. B. derived_from) für den zweiten Pass abtrennen.
    m2m_pending = {f: (data.pop(f, None) or []) for f in spec.get("m2m", {})}
    resolved = {}
    for fk_field, fk_def in spec["fks"].items():
        fk_model, fk_key = fk_def[0], fk_def[1]
        optional = "optional" in fk_def[2:]
        val = data.pop(fk_field, None)
        obj = fk_model.objects.filter(**{fk_key: val}).first() if val else None
        if val and not obj and not optional:
            raise ConfigImportError(
                f"Referenz nicht gefunden: {fk_field}={val} "
                f"(erst {fk_model.__name__} importieren).")
        resolved[fk_field] = obj
    key = spec["key"]
    key_val = data.get(key)
    if not key_val:
        if model is MCPToken:
            data["token"] = MCPToken.new_token()
            key_val = data["token"]
        else:
            raise ConfigImportError(f"Schlüsselfeld '{key}' fehlt in einem Item.")
    # Lookup ggf. um den Scope-FK ergänzen (WorkItem: project + identifier).
    scope_fk = spec.get("scope_fk")
    lookup = {key: key_val}
    if scope_fk:
        lookup[scope_fk] = resolved.get(scope_fk)
    defaults = {k: v for k, v in data.items() if k != key}
    defaults.update({k: v for k, v in resolved.items() if k != scope_fk})
    obj, created = model.objects.update_or_create(**lookup, defaults=defaults)
    return obj, created, m2m_pending


def _apply_m2m(model, obj, m2m_pending: dict) -> None:
    """Zweiter Pass: setzt die M2M-Beziehungen (Selbstreferenz über natürl. Schlüssel)."""
    spec = SPEC[_MODEL_TO_TYPE[model]]
    scope_fk = spec.get("scope_fk")
    for field, rel_key in spec.get("m2m", {}).items():
        keys = m2m_pending.get(field) or []
        if not keys:
            getattr(obj, field).clear()
            continue
        flt = {f"{rel_key}__in": keys}
        if scope_fk:
            flt[scope_fk] = getattr(obj, scope_fk)
        getattr(obj, field).set(list(model.objects.filter(**flt)))


def import_obj(model, payload: dict):
    """Einzel-Import: genau ein Item (`item`, oder `items` mit Länge 1)."""
    _validate_header(model, payload)
    item = payload.get("item")
    if item is None:
        items = payload.get("items") or []
        if len(items) != 1:
            raise ConfigImportError(
                "Einzel-Import erwartet genau einen Datensatz ('item').")
        item = items[0]
    obj, created, m2m = _import_one(model, item)
    _apply_m2m(model, obj, m2m)
    return obj, created


def import_type(model, payload: dict) -> dict:
    """Importiert alle `items` (oder einzelnes `item`) aus einem Typ-JSON.

    Transaktional: schlägt ein Datensatz fehl (z. B. fehlende Referenz), wird der
    GESAMTE Import zurückgerollt – kein halber Stand.
    """
    from django.db import transaction
    with transaction.atomic():
        return _import_type_inner(model, payload)


def _import_type_inner(model, payload: dict) -> dict:
    _validate_header(model, payload)
    items = payload.get("items")
    if items is None:
        if payload.get("item") is not None:
            items = [payload["item"]]
        else:
            raise ConfigImportError("Feld 'items' fehlt (Liste der Datensätze).")

    created = updated = 0
    pending = []
    for it in items:
        obj, was_created, m2m = _import_one(model, it)
        pending.append((obj, m2m))
        if was_created:
            created += 1
        else:
            updated += 1
    # Zweiter Pass: M2M setzen, wenn alle Items des Sets existieren
    # (derived_from kann auf andere Items derselben Datei zeigen).
    for obj, m2m in pending:
        _apply_m2m(model, obj, m2m)
    return {"created": created, "updated": updated, "total": created + updated}
