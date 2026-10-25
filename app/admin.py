import json

from django.contrib import admin
from django.contrib import messages as admin_messages
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse

from app import config_io


class JSONExchangeAdmin:
    """
    Mixin für JSON-Austausch im Admin – primär PRO TYP, zusätzlich pro Datensatz:
    - pro TYP (Liste, oben rechts): „JSON exportieren" lädt ALLE Datensätze des
      Typs in einer Datei; „JSON importieren" liest eine solche Datei ein
      (update_or_create je Datensatz, Typ über `_header.type` validiert).
    - pro DATENSATZ (zusätzlich): Spalte „⬇ JSON" und Button auf der
      Change-Seite laden genau einen Datensatz.
    Nur für Administratoren (Admin-Login vorausgesetzt).
    """
    change_form_template = "admin/jsonio_change_form.html"
    change_list_template = "admin/jsonio_change_list.html"

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        mine = [
            # Typ-Ebene (ganze Tabelle)
            path("export-json/",
                 self.admin_site.admin_view(self.export_type_view),
                 name="%s_%s_exporttype" % info),
            path("import-json/",
                 self.admin_site.admin_view(self.import_type_view),
                 name="%s_%s_importtype" % info),
            # Einzel-Datensatz
            path("<path:object_id>/export-json/",
                 self.admin_site.admin_view(self.export_obj_view),
                 name="%s_%s_exportjson" % info),
        ]
        return mine + super().get_urls()

    # --- Typ-Ebene -------------------------------------------------------
    def export_type_view(self, request):
        data = config_io.export_type(self.model)
        resp = JsonResponse(data, json_dumps_params={"indent": 2, "ensure_ascii": False})
        tname = config_io.type_for(self.model)
        resp["Content-Disposition"] = f'attachment; filename="{tname}.json"'
        return resp

    def import_type_view(self, request):
        info = self.model._meta.app_label, self.model._meta.model_name
        if request.method == "POST":
            if request.FILES.get("file"):
                raw = request.FILES["file"].read().decode("utf-8", "ignore")
            else:
                raw = request.POST.get("json", "")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self.message_user(request, f"Kein gültiges JSON: {exc}", admin_messages.ERROR)
            else:
                try:
                    res = config_io.import_type(self.model, payload)
                    self.message_user(
                        request,
                        f"Import OK: {res['created']} neu, {res['updated']} aktualisiert "
                        f"({res['total']} gesamt).",
                        admin_messages.SUCCESS)
                    return HttpResponseRedirect(
                        reverse("admin:%s_%s_changelist" % info))
                except config_io.ConfigImportError as exc:
                    self.message_user(request, str(exc), admin_messages.ERROR)
        ctx = dict(self.admin_site.each_context(request),
                   opts=self.model._meta,
                   title=f"{self.model._meta.verbose_name}: JSON importieren (ganzer Typ)",
                   type_name=config_io.type_for(self.model))
        return TemplateResponse(request, "admin/jsonio_import.html", ctx)

    # --- Einzel-Datensatz ------------------------------------------------
    def export_obj_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, "Objekt nicht gefunden.", admin_messages.ERROR)
            return HttpResponseRedirect("../../")
        data = config_io.export_obj(obj)
        resp = JsonResponse(data, json_dumps_params={"indent": 2, "ensure_ascii": False})
        tname = config_io.type_for(self.model)
        resp["Content-Disposition"] = f'attachment; filename="{tname}-{obj.pk}.json"'
        return resp

    @admin.display(description="Export")
    def export_link(self, obj):
        from django.utils.html import format_html
        info = self.model._meta.app_label, self.model._meta.model_name
        url = reverse("admin:%s_%s_exportjson" % info, args=[obj.pk])
        return format_html('<a class="button" href="{}">⬇ JSON</a>', url)

    def get_list_display(self, request):
        ld = list(super().get_list_display(request))
        if "export_link" not in ld:
            ld.append("export_link")
        return ld

from .models import (
    Customer, Project, WorkItem, NormClause, NormLink, ChatSession, ChatMessage,
    ProjectDocument, ProjectMembership, MCPToken, EmailSettings, LLMRoleDescription,
    FeedbackRequest, FeedbackStatus, WorkerBackend, WorkItemHistory, LifecycleEvent,
    Keyword, KeywordLink, EmbeddingChunk, SalinarTask, EmbeddedImage,
)


@admin.register(SalinarTask)
class SalinarTaskAdmin(admin.ModelAdmin):
    """Event-getriebene Salinar-Aufgaben (Upload → Tag, Generate → Norm-Abgleich)."""
    list_display = ("id", "project", "kind", "status", "document", "work_item",
                    "created_at", "processed_at")
    list_filter = ("status", "kind", "project")
    search_fields = ("ref", "note", "work_item__identifier")
    readonly_fields = ("created_at", "processed_at")
    date_hierarchy = "created_at"


@admin.register(LLMRoleDescription)
class LLMRoleDescriptionAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    list_display = ("get_role_display", "iec_reference", "short", "updated_at")
    readonly_fields = ("updated_at",)

    @admin.display(description="Beschreibung")
    def short(self, obj):
        return (obj.description[:80] + "…") if len(obj.description) > 80 else obj.description


@admin.register(EmailSettings)
class EmailSettingsAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    from .forms import EmailSettingsForm
    form = EmailSettingsForm
    list_display = ("label", "host", "port", "auth_display", "encryption_display",
                    "from_email", "active")
    fieldsets = (
        (None, {"fields": ("label", "active")}),
        ("Server", {"fields": (("host", "port"), ("use_tls", "use_ssl"), "timeout")}),
        ("Authentifizierung", {
            "fields": ("username", "password"),
            "description": "Leer lassen, wenn der Mailserver KEINE Authentifizierung "
                           "verlangt (offener Relay). Sonst Benutzer und Passwort setzen.",
        }),
        ("Absender", {"fields": ("from_email",)}),
    )
    actions = ["send_test_mail"]

    @admin.display(description="Auth")
    def auth_display(self, obj):
        return "mit Auth" if obj.username else "ohne Auth"

    @admin.display(description="Verschlüsselung")
    def encryption_display(self, obj):
        return "STARTTLS" if obj.use_tls else ("SSL" if obj.use_ssl else "keine")

    @admin.action(description="Test-E-Mail an den Absender senden")
    def send_test_mail(self, request, queryset):
        from django.core.mail import send_mail
        for s in queryset:
            try:
                send_mail(
                    subject="ELISA SMTP-Test",
                    message=f"Test über {s.host}:{s.port} erfolgreich.",
                    from_email=s.from_email,
                    recipient_list=[s.from_email],
                    fail_silently=False,
                )
                self.message_user(request, f"Testmail über {s.host} gesendet.",
                                  admin_messages.SUCCESS)
            except Exception as exc:
                self.message_user(request, f"Fehler über {s.host}: {exc}",
                                  admin_messages.ERROR)


@admin.register(MCPToken)
class MCPTokenAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    """Konnektivitätsverwaltung für den MCP-Server (SSE, Bearer-Token)."""
    change_form_template = "admin/mcptoken_change_form.html"
    actions = ["regenerate_token"]
    list_display = ("name", "masked_token", "scope", "access", "active", "project", "last_used")
    list_filter = ("active", "scope", "access", "project")
    search_fields = ("name",)
    readonly_fields = ("token", "created_at", "last_used", "connection_json")
    fields = ("name", "project", "scope", "access", "active", "token",
              "connection_json", "created_at", "last_used")

    def has_delete_permission(self, request, obj=None):
        # Tokens geschützter Endpunkte (Salinar/Übersetzer) sind nicht löschbar.
        if obj is not None and obj.worker_backends.filter(protected=True).exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        mine = [path("<path:object_id>/regenerate/",
                     self.admin_site.admin_view(self.regenerate_view),
                     name="%s_%s_regenerate" % info),
                path("<path:object_id>/mcpb/",
                     self.admin_site.admin_view(self.mcpb_view),
                     name="%s_%s_mcpb" % info)]
        return mine + super().get_urls()

    def mcpb_view(self, request, object_id):
        """
        Liefert eine installierbare **.mcpb** (Desktop-Extension) für diese
        Persona: bridged per `npx mcp-remote` auf unseren Remote-SSE-Server,
        Bearer-Token vorbelegt. In Claude Desktop: Extension installieren.
        """
        import io
        import zipfile
        from app import plugin_bundle
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, "Token nicht gefunden.", admin_messages.ERROR)
            return HttpResponseRedirect("../../")
        name, files = plugin_bundle.mcpb(obj)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, content in files.items():          # manifest.json im Wurzel
                z.writestr(rel, content)
        resp = HttpResponse(buf.getvalue(), content_type="application/octet-stream")
        resp["Content-Disposition"] = f'attachment; filename="{name}.mcpb"'
        return resp

    def regenerate_view(self, request, object_id):
        info = self.model._meta.app_label, self.model._meta.model_name
        obj = self.get_object(request, object_id)
        if obj is None:
            self.message_user(request, "Token nicht gefunden.", admin_messages.ERROR)
            return HttpResponseRedirect("../../")
        if request.method == "POST":
            obj.token = MCPToken.new_token()
            obj.save(update_fields=["token"])
            self.message_user(
                request,
                f"Neues Bearer-Token erzeugt. Verbundene Clients müssen es übernehmen. "
                f"Neues Token: {obj.token}", admin_messages.SUCCESS)
            return HttpResponseRedirect(
                reverse("admin:%s_%s_change" % info, args=[obj.pk]))
        ctx = dict(self.admin_site.each_context(request), opts=self.model._meta,
                   original=obj, title="Token neu erzeugen?",
                   backends=list(obj.worker_backends.all()))
        return TemplateResponse(request, "admin/mcptoken_regenerate.html", ctx)

    @admin.action(description="Token neu erzeugen (Bearer rotieren)")
    def regenerate_token(self, request, queryset):
        names = []
        for t in queryset:
            t.token = MCPToken.new_token()
            t.save(update_fields=["token"])
            names.append(t.name)
        self.message_user(
            request, f"{len(names)} Token neu erzeugt: {', '.join(names)}. "
            "Alte Bearer sind ungültig – Clients/WorkerBackends übernehmen den neuen Wert.",
            admin_messages.SUCCESS)

    # Öffentliche MCP-Basis (hinter nginx). Der V-Modell-Scope wird an die URL
    # angehängt: <base>/<scope>/sse.  Per env überschreibbar.
    import os as _os
    MCP_BASE = _os.getenv("MCP_PUBLIC_BASE", "http://192.168.88.252/mcp")

    @admin.display(description="Token")
    def masked_token(self, obj):
        return f"{obj.token[:6]}…{obj.token[-4:]}" if obj.token else "—"

    @admin.display(description="Verbindung (komplettes JSON)")
    def connection_json(self, obj):
        import json
        from django.utils.html import escape
        from django.utils.safestring import mark_safe
        if not obj.token:
            return "— Token wird beim Speichern erzeugt; danach erscheint hier das vollständige JSON —"
        # Projekt + V-Modell-Scope sind Teil der URL: <base>/<projekt>/<scope>/sse
        sse_url = f"{self.MCP_BASE}/{obj.url_path}/sse"
        server_name = (f"{obj.project.key}-{obj.scope_slug}"
                       if obj.project_id else f"elisa-{obj.scope_slug}")
        config = {
            "mcpServers": {
                server_name: {
                    "type": "sse",
                    "url": sse_url,
                    "headers": {"Authorization": f"Bearer {obj.token}"},
                }
            }
        }
        pretty = json.dumps(config, indent=2, ensure_ascii=False)
        elem_id = f"mcp-json-{obj.pk}"
        # JS bewusst ohne doppelte Anführungszeichen, damit es im onclick="" steht.
        onclick = (
            "var t=document.getElementById('%s');t.focus();t.select();"
            "t.setSelectionRange(0,99999);"
            "try{navigator.clipboard.writeText(t.value)}catch(e){document.execCommand('copy')}"
            "var b=this;b.textContent='\\u2713 Kopiert';"
            "setTimeout(function(){b.textContent='JSON kopieren'},1500);return false;" % elem_id
        )
        html = (
            '<p class="help">Connection-String für ein externes LLM / MCP-Client '
            '(z. B. Claude Desktop). Server starten: <code>python -m mcp_server.server</code>.</p>'
            f'<textarea id="{elem_id}" readonly rows="11" '
            'style="width:100%;font-family:monospace" onclick="this.select()">'
            f'{escape(pretty)}</textarea><br>'
            f'<button type="button" class="button" style="margin-top:6px" '
            f'onclick="{onclick}">JSON kopieren</button>'
        )
        return mark_safe(html)

    def save_model(self, request, obj, form, change):
        if not obj.token:
            obj.token = MCPToken.new_token()
        super().save_model(request, obj, form, change)


@admin.register(ProjectDocument)
class ProjectDocumentAdmin(admin.ModelAdmin):
    list_display = ("__str__", "project", "kind", "is_static", "uploaded_by", "uploaded_at")
    list_filter = ("kind", "is_static", "project")


@admin.register(ProjectMembership)
class ProjectMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "role", "added_at")
    list_filter = ("role", "project")


@admin.register(Customer)
class CustomerAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    list_display = ("name", "number", "country", "contact_person", "archived")
    list_filter = ("archived", "country")
    search_fields = ("name", "number", "vat_id", "contact_person", "contact_email")
    prepopulated_fields = {"number": ("name",)}


@admin.register(Project)
class ProjectAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    list_display = ("name", "key", "customer", "personas", "archived", "created_at")
    list_filter = ("archived", "customer")
    search_fields = ("name", "key")
    prepopulated_fields = {"key": ("name",)}
    actions = ["ensure_standard_personas"]

    @admin.display(description="Standard-Personas")
    def personas(self, obj):
        """Kontrolle: hat das Projekt seine Standard-Personas? (Salinar je Projekt,
        Dragoman global)."""
        from django.utils.html import format_html
        sal = WorkerBackend.objects.filter(handle="salinar", active=True,
                                           token__project=obj).exists()
        drag = WorkerBackend.objects.filter(handle="dragoman", active=True).exists()
        return format_html(
            '<span style="color:{}">{} Salinar</span> · <span style="color:{}">{} Dragoman</span>',
            "#198754" if sal else "#dc3545", "●" if sal else "○",
            "#198754" if drag else "#dc3545", "●" if drag else "○")

    @admin.action(description="Standard-Personas sicherstellen (Salinar je Projekt + Dragoman global)")
    def ensure_standard_personas(self, request, queryset):
        from app.apps import ensure_salinar_for, ensure_dragoman
        ensure_dragoman(None)
        for p in queryset:
            ensure_salinar_for(p)
        self.message_user(
            request, f"Standard-Personas sichergestellt für {queryset.count()} "
            "Projekt(e) (Salinar je Projekt) + Dragoman (global).")


class _ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    def has_add_permission(self, request, obj=None):
        return False
    def has_change_permission(self, request, obj=None):
        return False


class LifecycleEventInline(_ReadOnlyInline):
    model = LifecycleEvent
    fk_name = "work_item"
    fields = ("at", "from_state", "to_state", "iteration", "by", "note")
    readonly_fields = fields
    ordering = ("-at",)
    verbose_name_plural = "Status-Historie (Lifecycle)"


class WorkItemHistoryInline(_ReadOnlyInline):
    model = WorkItemHistory
    fields = ("at", "kind", "field", "old_value", "new_value", "by", "note")
    readonly_fields = fields
    ordering = ("-at",)
    verbose_name_plural = "Inhalts-Historie (jede Änderung)"


def _exhibit_preview(obj):
    """Kleine Inline-Vorschau: Bild als <img>, Tabelle als Hinweis."""
    from django.utils.html import format_html
    if obj.kind == EmbeddedImage.Kind.TABLE:
        return format_html('<span class="text-muted">[{}]</span>',
                           "Tabelle" if obj.table_html else "Tabelle (leer)")
    uri = obj.data_uri
    if uri:
        return format_html('<img src="{}" style="max-height:60px;max-width:120px;'
                           'border:1px solid #dee2e6;border-radius:3px">', uri)
    return format_html('<span class="text-muted">—</span>')


class EmbeddedImageInline(admin.TabularInline):
    model = EmbeddedImage
    extra = 0
    fields = ("preview", "kind", "number", "caption", "attribution",
              "mime", "data", "table_html", "order")
    readonly_fields = ("preview",)

    @admin.display(description="Vorschau")
    def preview(self, obj):
        return _exhibit_preview(obj) if obj and obj.pk else "—"


@admin.register(EmbeddedImage)
class EmbeddedImageAdmin(admin.ModelAdmin):
    list_display = ("__str__", "work_item", "kind", "number", "caption",
                    "attribution", "preview")
    list_filter = ("kind", "work_item__project")
    search_fields = ("caption", "attribution", "work_item__identifier")
    readonly_fields = ("preview", "created_at")
    autocomplete_fields = ("work_item",)

    @admin.display(description="Vorschau")
    def preview(self, obj):
        return _exhibit_preview(obj)


@admin.register(WorkItem)
class WorkItemAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    list_display = ("identifier", "project", "phase", "title", "status",
                    "generated_by_llm", "is_orphan")
    list_filter = ("project", "phase", "status", "generated_by_llm")
    search_fields = ("identifier", "title", "body")
    filter_horizontal = ("derived_from",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [EmbeddedImageInline, LifecycleEventInline, WorkItemHistoryInline]

    @admin.display(boolean=True, description="Orphan")
    def is_orphan(self, obj):
        return obj.is_orphan

    def save_model(self, request, obj, form, change):
        from app import history
        if change and obj.pk:
            before = history.snapshot(self.model.objects.get(pk=obj.pk))
            super().save_model(request, obj, form, change)
            history.record_changes(obj, before, by=request.user,
                                   note="Bearbeitung im Admin")
        else:
            super().save_model(request, obj, form, change)
            history.record_created(obj, by=request.user, note="im Admin angelegt")


@admin.register(WorkItemHistory)
class WorkItemHistoryAdmin(admin.ModelAdmin):
    """Lückenlose Item-Historie – nur lesen (append-only, nie ändern/löschen)."""
    list_display = ("at", "item", "kind", "field", "by", "short_note")
    list_filter = ("kind", "item__project", "field")
    search_fields = ("item__identifier", "old_value", "new_value", "note")
    date_hierarchy = "at"
    ordering = ("-at",)

    @admin.display(description="Notiz")
    def short_note(self, obj):
        return obj.note or (f"{obj.old_value[:30]} → {obj.new_value[:30]}"
                            if obj.field else "")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NormClause)
class NormClauseAdmin(admin.ModelAdmin):
    list_display = ("standard", "clause", "source_page")
    search_fields = ("standard", "clause", "text")


@admin.register(NormLink)
class NormLinkAdmin(admin.ModelAdmin):
    list_display = ("item", "clause", "confidence", "confirmed")
    list_filter = ("confirmed",)


@admin.register(EmbeddingChunk)
class EmbeddingChunkAdmin(admin.ModelAdmin):
    """
    Vektor-Index (pgvector). Read-only-Browse + **Norm-Index neu aufbauen**
    (Reindex aus incoming/ im Hintergrund). Inhalts-Dubletten über SHA-256.
    """
    change_list_template = "admin/embeddingchunk_change_list.html"
    list_display = ("collection", "source", "page", "kind", "short_hash")
    list_filter = ("collection", "kind")
    search_fields = ("source", "content_hash")

    @admin.display(description="SHA-256")
    def short_hash(self, obj):
        return (obj.content_hash[:10] + "…") if obj.content_hash else "—"

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        mine = [path("reindex/", self.admin_site.admin_view(self.reindex_view),
                     name="%s_%s_reindex" % info)]
        return mine + super().get_urls()

    def reindex_view(self, request):
        """Stößt build_rag_index im Hintergrund an (PDFs aus incoming/ → pgvector)."""
        import subprocess
        import sys
        from django.conf import settings
        args = [sys.executable, str(settings.BASE_DIR / "manage.py"), "build_rag_index"]
        try:
            log = open(settings.DATA_DIR / "rag_index.log", "ab")
        except OSError:
            log = subprocess.DEVNULL
        try:
            subprocess.Popen(args, cwd=str(settings.BASE_DIR), stdout=log, stderr=log)
            self.message_user(
                request, "Norm-Index-Neuaufbau gestartet (Hintergrund). PDFs aus "
                "incoming/ werden neu eingebettet; Dubletten (gleicher SHA-256) "
                "werden übersprungen.", admin_messages.SUCCESS)
        except Exception as exc:
            self.message_user(request, f"Start fehlgeschlagen: {exc}", admin_messages.ERROR)
        return HttpResponseRedirect("../")


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("text", "label", "link_count", "created_at")
    search_fields = ("text", "label")

    @admin.display(description="Verknüpfungen")
    def link_count(self, obj):
        return obj.links.count()


@admin.register(KeywordLink)
class KeywordLinkAdmin(admin.ModelAdmin):
    """Schlagwort-Verknüpfungen: LLM schlägt vor (confirmed=False), Mensch bestätigt."""
    list_display = ("keyword", "target", "confidence", "generated_by_llm",
                    "confirmed", "confirmed_by")
    list_filter = ("confirmed", "generated_by_llm", "work_item__project")
    search_fields = ("keyword__text", "work_item__identifier")
    actions = ["confirm_links"]

    @admin.display(description="Ziel")
    def target(self, obj):
        return obj.work_item.identifier if obj.work_item_id else (
            str(obj.document) if obj.document_id else "—")

    @admin.action(description="Ausgewählte Schlagwörter bestätigen (menschlich)")
    def confirm_links(self, request, queryset):
        n = queryset.update(confirmed=True, confirmed_by=request.user)
        self.message_user(request, f"{n} Schlagwort-Verknüpfung(en) bestätigt.",
                          admin_messages.SUCCESS)


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("role", "author", "author_label", "content", "generated_by_llm",
              "llm_model", "created_at")
    readonly_fields = ("created_at",)
    ordering = ("created_at",)


class ChatTypeFilter(admin.SimpleListFilter):
    """Filtert Chats nach Typ (abgeleitet aus related_item/shared/owner)."""
    title = "Typ"
    parameter_name = "ctype"

    def lookups(self, request, model_admin):
        return [("item", "Item-Chat"), ("project", "Projekt-Chat"), ("rag", "RAG-Chat")]

    def queryset(self, request, qs):
        from django.db.models import Q
        v = self.value()
        if v == "item":
            return qs.filter(related_item__isnull=False)
        if v == "project":
            return qs.filter(related_item__isnull=True).filter(
                Q(shared=True) | Q(owner__isnull=True))
        if v == "rag":
            return qs.filter(related_item__isnull=True, shared=False, owner__isnull=False)
        return qs


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    """Chats administrieren: Item-Chats, Projekt-Chats (geteilt) und persönliche."""
    list_display = ("id", "kind", "project", "related_item", "owner", "title",
                    "msg_count", "updated_at")
    list_filter = (ChatTypeFilter, "shared", "project")
    search_fields = ("title", "related_item__identifier", "owner__username",
                     "messages__content")     # auch nach Chat-INHALT suchen

    def get_search_results(self, request, queryset, search_term):
        # messages__content über JOIN → Duplikate vermeiden.
        qs, use_distinct = super().get_search_results(request, queryset, search_term)
        return qs, True
    date_hierarchy = "updated_at"
    inlines = [ChatMessageInline]

    @admin.display(description="Typ")
    def kind(self, obj):
        if obj.related_item_id:
            return "Item-Chat"
        return "Projekt-Chat" if obj.shared else "Persönlich"

    @admin.display(description="Nachrichten")
    def msg_count(self, obj):
        return obj.messages.count()


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Einzelne Chat-Nachrichten durchsuchen/bereinigen."""
    list_display = ("id", "session", "role", "who", "short", "generated_by_llm",
                    "created_at")
    list_filter = ("role", "generated_by_llm", "session__project",
                   "session__related_item")
    search_fields = ("content", "author_label", "author__username",
                     "session__related_item__identifier")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"

    @admin.display(description="Von")
    def who(self, obj):
        if obj.author_id:
            return obj.author.get_username()
        return obj.author_label or obj.llm_model or "—"

    @admin.display(description="Inhalt")
    def short(self, obj):
        return (obj.content or "")[:80]


@admin.register(FeedbackRequest)
class FeedbackRequestAdmin(admin.ModelAdmin):
    """
    Beobachtung der poll-freien Write-time-Feedback-Pipeline:
    offen (PENDING) → vom Worker per SSE-Push übernommen (CLAIMED) →
    beantwortet (ANSWERED). Reine Mechanik – hier wird KEIN Inhalt geschrieben,
    nur Toasts/Status. Hängengebliebene Anfragen lassen sich neu einreihen.
    """
    list_display = ("id", "project", "item_ref", "phase_role", "status_badge",
                    "source", "answered_by", "toast_count", "created_at", "answered_at")
    list_filter = ("status", "source", "project")
    search_fields = ("draft", "answered_by")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    actions = ["requeue", "mark_obsolete"]
    readonly_fields = ("project", "item", "status", "source", "answered_by",
                       "created_at", "answered_at", "draft", "neighbours_pretty",
                       "toasts_pretty")
    fields = ("project", "item", "status", "source", "answered_by",
              "created_at", "answered_at", "draft", "neighbours_pretty",
              "toasts_pretty")

    @admin.display(description="Item")
    def item_ref(self, obj):
        return obj.item.identifier if obj.item_id else "—"

    @admin.display(description="V-Schritt")
    def phase_role(self, obj):
        return obj.item.phase if obj.item_id else "—"

    @admin.display(description="Status")
    def status_badge(self, obj):
        from django.utils.html import format_html
        color = {"PENDING": "#b58900", "CLAIMED": "#268bd2",
                 "ANSWERED": "#859900"}.get(obj.status, "#666")
        return format_html('<b style="color:{}">{}</b>', color, obj.get_status_display())

    @admin.display(description="Toasts")
    def toast_count(self, obj):
        return len(obj.toasts or [])

    @admin.display(description="Nachbar-Items")
    def neighbours_pretty(self, obj):
        return self._pre(obj.neighbours)

    @admin.display(description="Toasts (JSON)")
    def toasts_pretty(self, obj):
        return self._pre(obj.toasts)

    @staticmethod
    def _pre(value):
        from django.utils.html import format_html
        return format_html('<pre style="white-space:pre-wrap;margin:0">{}</pre>',
                           json.dumps(value or [], indent=2, ensure_ascii=False))

    @admin.action(description="Erneut in die Warteschlange (→ PENDING)")
    def requeue(self, request, queryset):
        n = queryset.update(status=FeedbackStatus.PENDING, toasts=[], source="",
                            answered_by="", answered_at=None)
        self.message_user(
            request, f"{n} Anfrage(n) neu eingereiht – der Worker bekommt sie erneut "
            "per SSE-Push.", admin_messages.SUCCESS)

    @admin.action(description="Als beantwortet/erledigt markieren (ohne Toasts)")
    def mark_obsolete(self, request, queryset):
        from django.utils import timezone
        n = queryset.update(status=FeedbackStatus.ANSWERED, answered_by="admin",
                            answered_at=timezone.now())
        self.message_user(request, f"{n} Anfrage(n) abgeschlossen.",
                          admin_messages.SUCCESS)

    def has_add_permission(self, request):
        return False  # FeedbackRequests entstehen nur aus dem Editor


def _fetch_provider_models(obj):
    """Fragt die verfügbaren Modelle beim Provider ab (Anthropic bzw. OpenAI-kompat.)."""
    import httpx
    if obj.protocol == "claude":
        r = httpx.get("https://api.anthropic.com/v1/models",
                      headers={"x-api-key": obj.api_key or "",
                               "anthropic-version": "2023-06-01"}, timeout=15)
        r.raise_for_status()
        return [m.get("id") for m in r.json().get("data", [])]
    base = (obj.effective_base_url or "").rstrip("/")
    if not base:
        raise ValueError("Keine Base-URL gesetzt.")
    headers = {"Authorization": f"Bearer {obj.api_key}"} if obj.api_key else {}
    r = httpx.get(base + "/models", headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    items = data.get("data", []) if isinstance(data, dict) else data
    return [(m.get("id") if isinstance(m, dict) else m) for m in items]


from django import forms


class WorkerBackendForm(forms.ModelForm):
    """Erweitert das Admin-Formular um Inline-Buttons direkt an den Feldern
    („API-Key erstellen" am api_key, „Modelle abrufen" am model) – im Gegensatz
    zu object-tools erscheinen sie auf Hinzufügen UND Ändern."""
    class Meta:
        model = WorkerBackend
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        from django.utils.safestring import mark_safe
        from django.urls import reverse
        super().__init__(*args, **kwargs)
        if "api_key" in self.fields:
            f = self.fields["api_key"]
            f.help_text = mark_safe((f.help_text or "") +
                ' &nbsp;<a href="#" id="gen-key-btn" class="button">Secret-Key generieren</a>'
                ' &nbsp;<a href="#" id="get-key-btn" class="button" target="_blank"'
                ' rel="noopener">In Provider-Console erstellen ↗</a>')
        if "model" in self.fields:
            f = self.fields["model"]
            try:
                url = reverse("admin:app_workerbackend_getmodels")
            except Exception:
                url = ""
            f.help_text = mark_safe((f.help_text or "") +
                f' &nbsp;<a href="#" id="get-models-btn" class="button"'
                f' data-url="{url}">Modelle abrufen</a>')


@admin.register(WorkerBackend)
class WorkerBackendAdmin(JSONExchangeAdmin, admin.ModelAdmin):
    """
    Verwaltung der Inferenz-Backends für den Persona-Worker. Claude (Anthropic)
    oder beliebige OpenAI-kompatible (ChatGPT, DeepSeek, Ollama, LM Studio …).
    Über den MCP-Token an Projekt + V-Schritt gebunden. JSON-Austausch wie bei
    den übrigen Einstellungen (Dev → Live). Button „Modelle abrufen" holt die
    verfügbaren Modelle direkt vom Provider.
    """
    change_form_template = "admin/workerbackend_change_form.html"
    form = WorkerBackendForm
    list_filter = ("provider", "active", "protected")
    search_fields = ("name", "model", "base_url")
    fieldsets = (
        (None, {"fields": ("name", "provider", "active")}),
        ("Modell & Zugang", {
            "fields": ("model", "base_url", "api_key"),
            "description": "„Modelle abrufen“ füllt die Combobox am Modell-Feld; "
                           "Buttons zum Erzeugen/Holen des API-Keys stehen am API-Key.",
        }),
        ("MCP-Anbindung", {"fields": ("token", "mcp_base")}),
        ("Identität & Schutz", {"fields": ("handle", "protected")}),
        ("Effektive Konfiguration", {"fields": ("effective",)}),
    )
    readonly_fields = ("effective",)
    list_display = ("name", "provider", "handle_disp", "model_display", "queue",
                    "protocol_display", "masked_key", "protected", "active")

    @admin.display(description="@-Handle")
    def handle_disp(self, obj):
        return obj.effective_handle

    def has_delete_permission(self, request, obj=None):
        # Geschützte Endpunkte (z. B. Salinar) sind nicht löschbar.
        if obj is not None and getattr(obj, "protected", False):
            return False
        return super().has_delete_permission(request, obj)

    def get_urls(self):
        info = self.model._meta.app_label, self.model._meta.model_name
        mine = [path("get-models/",
                     self.admin_site.admin_view(self.get_models_view),
                     name="%s_%s_getmodels" % info)]
        return mine + super().get_urls()

    def get_models_view(self, request):
        """Modelle vom Provider abrufen – aus den FORMULARWERTEN (provider/api_key/
        base_url). Funktioniert auch auf dem Hinzufügen-Formular ohne Speichern."""
        g = request.POST if request.method == "POST" else request.GET
        obj = WorkerBackend(provider=g.get("provider", ""),
                            api_key=g.get("api_key", ""),
                            base_url=g.get("base_url", ""))
        # Neueste Claude-Connectoren laufen über OAuth/Abo – KEIN API-Key. Dann
        # kann die Anthropic-/v1/models-Abfrage nicht greifen → kuratierte Liste.
        if obj.protocol == "claude" and not (obj.api_key or "").strip():
            return JsonResponse({
                "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
                "provider": obj.get_provider_display(),
                "note": "Connector ohne API-Key – bekannte Modelle (manuell wählbar)."})
        try:
            models = sorted({m for m in _fetch_provider_models(obj) if m})
        except Exception as exc:
            return JsonResponse({"error": str(exc)[:300]}, status=502)
        return JsonResponse({"models": models, "provider": obj.get_provider_display()})

    @admin.display(description="Modell")
    def model_display(self, obj):
        return obj.effective_model + ("" if obj.model else "  (Default)")

    @admin.display(description="Protokoll")
    def protocol_display(self, obj):
        return obj.protocol

    @admin.display(description="Warteschlange")
    def queue(self, obj):
        t = obj.token
        return f"{t.project.key}/{t.scope_slug}" if t and t.project_id else "—"

    @admin.display(description="Key")
    def masked_key(self, obj):
        k = obj.api_key or ""
        return (k[:4] + "…" + k[-3:]) if len(k) > 8 else ("gesetzt" if k else "—")

    @admin.display(description="Effektive Konfiguration")
    def effective(self, obj):
        from django.utils.html import format_html
        t = obj.token
        queue = f"{t.project.key}/{t.scope_slug}" if t and t.project_id else "—"
        warn = "" if (not t or t.access == "WRITE") else \
            "  ⚠ Token ist nicht WRITE – Worker kann keine Toasts zurückschreiben!"
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0">Protokoll:  {}\n'
            'Base-URL:   {}\nModell:     {}\nMCP-Basis:  {}\n'
            'Endpunkt:   {}/{}/events{}</pre>',
            obj.protocol, obj.effective_base_url or "(Anthropic-API)",
            obj.effective_model, obj.effective_mcp_base,
            obj.effective_mcp_base, queue, warn)


# ── Admin-Index gliedern: logische Sektionen statt einer flachen „App"-Liste ──
_ADMIN_GROUPS = [
    ("Anforderungen & Traceability", ["WorkItem", "WorkItemHistory", "LifecycleEvent",
                                      "NormClause", "NormLink"]),
    ("Schlagwortkatalog & RAG", ["Keyword", "KeywordLink", "EmbeddingChunk"]),
    ("Chats", ["ChatSession", "ChatMessage"]),
    ("LLM, MCP & Worker", ["WorkerBackend", "MCPToken", "LLMRoleDescription",
                           "SalinarTask", "FeedbackRequest"]),
    ("Projekte, Kunden & Dokumente", ["Project", "Customer", "ProjectDocument",
                                      "ProjectMembership"]),
    ("Benutzer & System", ["UserProfile", "EmailSettings", "User", "Group"]),
]

_orig_get_app_list = admin.site.get_app_list


def _grouped_get_app_list(request, app_label=None):
    """Gruppiert die (sonst flache) App-Modellliste in benannte Sektionen."""
    app_list = _orig_get_app_list(request, app_label)
    if app_label:                       # einzelne App (App-Index) nicht umbauen
        return app_list
    models = {}
    for app in app_list:
        for m in app["models"]:
            models[m["object_name"]] = m
    out, used = [], set()
    for name, objs in _ADMIN_GROUPS:
        ms = [models[o] for o in objs if o in models]
        used.update(o for o in objs if o in models)
        if ms:
            out.append({"name": name, "app_label": "app", "app_url": "",
                        "has_module_perms": True, "models": ms})
    rest = [m for o, m in models.items() if o not in used]
    if rest:
        out.append({"name": "Weiteres", "app_label": "app", "app_url": "",
                    "has_module_perms": True, "models": rest})
    return out


admin.site.get_app_list = _grouped_get_app_list
