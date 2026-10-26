"""
Datenmodell für die SPEC/DESIGN-Automatisierung (V-Modell).

Kerngedanke:
  - Eine selbstreferenzierende Hierarchie von Arbeitsobjekten (WorkItem),
    die die vier absteigenden Ebenen abbildet.
  - Traceability als explizite Relationen (derived_from).
  - LLM-Entwürfe sind ein SEPARATER, nicht-verbindlicher Zustand:
    nichts wird APPROVED, bevor ein Mensch es freigibt.
  - Inhalt (body) stammt IMMER vom Menschen; das LLM verfasst ihn nie.
  - Norm-Bezug (RAG) als nachvollziehbarer, menschlich bestätigter Link.
"""

from django.db import models
from django.contrib.auth import get_user_model
from pgvector.django import VectorField, HnswIndex

User = get_user_model()


class Phase(models.TextChoices):
    """
    Die acht Punkte des V-Modells – links die spezifizierenden (absteigenden)
    Ebenen, rechts die verifizierenden Teststufen. Bezeichnungen normativ nach
    IEC 61508-3 §7 (Software-Sicherheitslebenszyklus, Bild 6) – EINE Quelle,
    überall verwendet (konsistent mit VModelRole).
    """
    # Linke Seite (spezifizierend)
    REQUIREMENT = "REQ", "Software-Sicherheitsanforderungen"
    SPECIFICATION = "SPEC", "Software-Systementwurf"
    ARCHITECTURE = "ARCH", "Software-Architektur"
    MODULE = "MOD", "Software-Modulentwurf"
    # Rechte Seite (verifizierend) – Partnerebene siehe VERIFY_PARTNER
    MODTEST = "MODTEST", "Software-Modultest"
    INTTEST = "INTTEST", "Integrationstest (HW/SW)"
    SYSTEST = "SYSTEST", "Software-Integrationstest"
    ACCTEST = "ACCTEST", "Software-Sicherheitsvalidierung"


# Teststufen (rechte V-Modell-Seite) und ihre Entwicklungs-Partnerebene (links).
# Ein Test-Item VERIFIZIERT Items seiner Partnerebene (REQ↔ACCTEST, SPEC↔SYSTEST,
# ARCH↔INTTEST, MOD↔MODTEST).
TEST_PHASES = {Phase.MODTEST, Phase.INTTEST, Phase.SYSTEST, Phase.ACCTEST}
VERIFY_PARTNER = {
    Phase.MODTEST: Phase.MODULE,
    Phase.INTTEST: Phase.ARCHITECTURE,
    Phase.SYSTEST: Phase.SPECIFICATION,
    Phase.ACCTEST: Phase.REQUIREMENT,
}


class VModelRole(models.TextChoices):
    """
    Die acht Punkte des V-Modells – als Rollen, in denen das LLM mitwirken kann.
    Links die spezifizierenden Ebenen, rechts die verifizierenden. Namen
    normativ nach IEC 61508-3 §7 (konsistent mit Phase).
    """
    REQ = "REQ", "Software-Sicherheitsanforderungen"
    SPEC = "SPEC", "Software-Systementwurf"
    ARCH = "ARCH", "Software-Architektur"
    MOD = "MOD", "Software-Modulentwurf"
    MODTEST = "MODTEST", "Software-Modultest"
    INTTEST = "INTTEST", "Integrationstest (HW/SW)"
    SYSTEST = "SYSTEST", "Software-Integrationstest"
    ACCTEST = "ACCTEST", "Software-Sicherheitsvalidierung"


# Rollenbeschreibungen umfassen die 8 V-Schritte PLUS die System-Personas. Wichtig:
# VModelRole bleibt rein die V-Schritte (es erzeugt u. a. die Worktree-Stufen) –
# die Personas leben NUR in dieser erweiterten Choices-Liste für LLMRoleDescription.
LLM_ROLE_CHOICES = list(VModelRole.choices) + [
    ("LUKAS", "Lukas – RAG-Assistent"),
    ("ESRA", "Esra – Normenrecherche"),
    ("TERTIUS", "Tertius – Übersetzer"),
    ("NATHAN", "Nathan – externes Audit"),
]


class LLMRoleDescription(models.Model):
    """
    Rollenbeschreibung (Persona/Anweisung) für das LLM je V-Modell-Rolle.
    Im Admin pflegbar. Wird dem LLM als System-Kontext mitgegeben – zusammen
    mit der Projektbeschreibung. Das LLM bleibt beratend/vorschlagend.
    """
    role = models.CharField(max_length=8, choices=LLM_ROLE_CHOICES, unique=True)
    iec_reference = models.CharField(
        "IEC-61508-Bezug", max_length=80, blank=True,
        help_text="Referenz zur IEC 61508, z. B. 'IEC 61508-3 §7.4.3'.")
    description = models.TextField(
        help_text="Wie soll sich das LLM in dieser Rolle verhalten? "
                  "(Aufgabe, Fokus, Normbezug). Kein verbindlicher Inhalt.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role"]
        verbose_name = "LLM-Rollenbeschreibung"
        verbose_name_plural = "LLM-Rollenbeschreibungen"

    def __str__(self):
        return f"LLM-Rolle: {self.get_role_display()}"


class ItemStatus(models.TextChoices):
    """
    Iterativer Lebenszyklus (gilt für WorkItems UND Projektdokumente):
        Entwurf → In Prüfung → (Überarbeitung ↺ zurück zur Prüfung)
                → Freigegeben → bei Änderung neue Revision → Entwurf;  + Überholt.
    Die Codes DRAFT/PROPOSED/APPROVED/OBSOLETE bleiben (Abwärtskompatibilität,
    CLAUDE.md Regel 2): APPROVED (= „Freigegeben") setzt menschlichen
    approved_by voraus und ist rechtegeschützt (PL/FSM).
    """
    DRAFT = "DRAFT", "Entwurf"
    PROPOSED = "PROPOSED", "In Prüfung"
    REWORK = "REWORK", "Überarbeitung"
    REVIEWED = "REVIEWED", "Reviewt"              # Review durch zweite Person (≠ Autor)
    APPROVED = "APPROVED", "Freigegeben"
    SIGNED = "SIGNED", "Signiert (eingefroren)"   # frozen – nur Admins dürfen noch ändern
    OBSOLETE = "OBSOLETE", "Überholt"


class Customer(models.Model):
    """
    Kunde (international). Ein Kunde kann mehrere Projekte (Mandanten) haben.
    Adressfelder bewusst international gehalten (Land als ISO-Code, frei
    formatierbare Region/PLZ, USt-IdNr./VAT, Sprache).
    """
    # ── Identität ──────────────────────────────────────────────────────────
    number = models.SlugField(max_length=32, unique=True)   # Kundennummer, z. B. "K-1042"
    name = models.CharField(max_length=255)                 # Firma / Organisation
    legal_form = models.CharField(max_length=64, blank=True)  # GmbH, Ltd., Inc., S.A. …

    # ── Anschrift (international) ───────────────────────────────────────────
    address_line1 = models.CharField("Straße / Adresszeile 1", max_length=255, blank=True)
    address_line2 = models.CharField("Adresszeile 2", max_length=255, blank=True)
    postal_code = models.CharField("PLZ / ZIP", max_length=32, blank=True)
    city = models.CharField("Stadt", max_length=128, blank=True)
    region = models.CharField("Region / Bundesland / State", max_length=128, blank=True)
    country = models.CharField("Land (ISO 3166, z. B. DE/US/CN)", max_length=2, blank=True)

    # ── Steuer / Recht ─────────────────────────────────────────────────────
    vat_id = models.CharField("USt-IdNr. / VAT / Tax ID", max_length=32, blank=True)
    registration_no = models.CharField("Handelsregister / Reg.-Nr.", max_length=64, blank=True)

    # ── Kontakt ────────────────────────────────────────────────────────────
    contact_person = models.CharField(max_length=255, blank=True)
    contact_email = models.EmailField(blank=True)
    phone = models.CharField("Telefon (international, z. B. +49 …)", max_length=64, blank=True)
    website = models.URLField(blank=True)

    # ── Sonstiges ──────────────────────────────────────────────────────────
    language = models.CharField("Sprache (ISO 639, z. B. de/en)", max_length=8,
                                blank=True, default="de")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def address_block(self):
        """Mehrzeilige Anschrift für Anzeige/Dokumente."""
        parts = [
            self.address_line1, self.address_line2,
            " ".join(p for p in [self.postal_code, self.city] if p),
            self.region, self.country,
        ]
        return "\n".join(p for p in parts if p)


class Project(models.Model):
    """
    Mandant / Projekt. Trennt die fachlichen Daten (WorkItems, Chats) mehrerer
    Vorhaben. Gehört zu einem Kunden. Der Norm-Pool (NormClause) und der
    RAG-Index sind global geteilt – Normen gelten projektübergreifend.
    """
    customer = models.ForeignKey(
        Customer, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="projects",
    )
    key = models.SlugField(max_length=32, unique=True)   # z. B. "sa2026-026"
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    # Mehrsprachigkeit: Primärsprache = Quellsprache (vom Menschen geschrieben);
    # eine Änderung darin wird automatisch in die übrigen `languages` übersetzt.
    primary_language = models.CharField("Primärsprache", max_length=8, default="",
                                        blank=True,
                                        help_text="ISO 639, z. B. de/en. Die normative "
                                        "Quellsprache; wird beim Hinzufügen der ersten "
                                        "Sprache gesetzt.")
    languages = models.JSONField("Unterstützte Sprachen", default=list, blank=True,
                                 help_text='ISO-Codes inkl. Primärsprache, z. B. ["de","en","fr"].')
    # NORMATIV vs. informativ je Sprache: normative Sprachen tragen den
    # maßgeblichen Wortlaut und dürfen NIE Ziel einer Übersetzung sein (eine
    # Übersetzung NACH einer normativen Sprache muss fehlschlagen). Default: die
    # Primärsprache ist normativ.
    normative_languages = models.JSONField("Normative Sprachen", default=list, blank=True,
                                           help_text='ISO-Codes, deren Inhalt NORMATIV ist '
                                           '(darf nicht übersetzt werden), z. B. ["de"].')
    created_at = models.DateTimeField(auto_now_add=True)
    archived = models.BooleanField(default=False)

    @property
    def target_languages(self):
        """Zielsprachen (alle außer der Primärsprache)."""
        return [l for l in (self.languages or []) if l and l != self.primary_language]

    def is_normative(self, code) -> bool:
        """Es gibt GENAU EINE normative Sprache = die Primärsprache (Projektsprache).
        Alle anderen sind informativ (übersetzbar). Mehrfach-Normativ ist
        logisch ausgeschlossen."""
        return bool(code) and code == self.primary_language

    class Meta:
        ordering = ["name"]

    def __str__(self):
        if self.customer_id:
            return f"{self.name} ({self.customer.name})"
        return self.name


class DocumentKind(models.TextChoices):
    """Art eines Projektdokuments."""
    PEP = "PEP", "PEP – Product Engineering Process"
    REQ = "REQ", "REQ – Kundenanforderungen"
    NORM = "NORM", "Norm / Standard"
    SPEC = "SPEC", "Spezifikation"
    TEST = "TEST", "Test / Nachweis"
    CERT = "CERT", "Zertifikat / Zulassung"
    AUDIT = "AUDIT", "Audit / extern (TÜV / Kunde / Sub)"
    CORR = "CORR", "Korrespondenz"
    OTHER = "OTHER", "Sonstiges"


class Confidentiality(models.TextChoices):
    """Vertraulichkeitsstufe (Klassifizierung)."""
    PUBLIC = "PUBLIC", "Öffentlich"
    INTERNAL = "INTERNAL", "Intern"
    CONFIDENTIAL = "CONFIDENTIAL", "Vertraulich"
    STRICT = "STRICT", "Streng vertraulich"


def project_doc_path(instance, filename):
    """
    Ablage-Abstraktion: der gespeicherte DATEINAME ist eine UUID (+ Original-
    Endung), damit NAMENSGLEICHE Dokumente sich NICHT überschreiben. Der
    Originalname wird separat in `ProjectDocument.original_name` gehalten
    (für Download/Index/Anzeige).
    """
    from uuid import uuid4
    from pathlib import PurePosixPath
    key = instance.project.key if instance.project_id else "unzugeordnet"
    ext = PurePosixPath(filename).suffix.lower()
    return f"project_docs/{key}/{uuid4().hex}{ext}"


class ProjectDocument(models.Model):
    """
    Dokumentenmanagement je Projekt. PEP/REQ sind statisch (kommen vom Kunden,
    werden im Tool nie verändert) und werden über den MCP-Server read-only
    bereitgestellt.
    """
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=8, choices=DocumentKind.choices,
                            default=DocumentKind.OTHER)
    # ── Klassifizierung ──────────────────────────────────────────────────
    confidentiality = models.CharField(
        max_length=12, choices=Confidentiality.choices,
        default=Confidentiality.INTERNAL)
    safety_relevant = models.BooleanField(default=False)
    revision = models.CharField(max_length=32, blank=True)  # z. B. "V1.1.2"

    title = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to=project_doc_path)
    original_name = models.CharField(max_length=255, blank=True)  # echter Dateiname (Anzeige/Download)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)  # SHA-256 der Datei
    is_static = models.BooleanField(default=True)  # kundengeliefert, read-only
    indexed_chunks = models.PositiveIntegerField(default=0)  # RAG-Status
    # Iterativer Lebenszyklus (auch über MCP les-/setzbar): Entwurf → Prüfung →
    # Überarbeitung → Freigegeben → (Revision) … Kennzeichnet den Bearbeitungsstand.
    status = models.CharField(max_length=10, choices=ItemStatus.choices,
                              default=ItemStatus.DRAFT)
    iteration = models.PositiveIntegerField(default=1)   # Zyklus-Iteration
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_note = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="uploaded_docs")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "-uploaded_at"]

    def __str__(self):
        return self.title or self.file.name.rsplit("/", 1)[-1]


class Role(models.TextChoices):
    """
    Projektrollen, FEST gemäß IEC 61508 (funktionale Sicherheit) verdrahtet.
    Die Norm fordert Kompetenz und – je nach SIL – Unabhängigkeit zwischen
    Entwurf, Verifikation, Validierung und Begutachtung (FSA). Dieser Satz ist
    fix; passende Django-Gruppen werden automatisch angelegt (siehe apps.py).
    """
    PROJECT_MANAGER = "PM", "Projektleitung"
    SAFETY_MANAGER = "FSM", "Funktionale-Sicherheits-Management (FSM)"
    DESIGNER = "DESIGN", "Entwurf / Realisierung"
    VERIFIER = "VERIF", "Verifikation"
    VALIDATOR = "VALID", "Validierung"
    ASSESSOR = "FSA", "Sicherheitsbegutachtung (FSA, unabhängig)"
    AUDITOR = "AUDIT", "Externes Audit (TÜV / Kunde / Sub)"


class UserProfile(models.Model):
    """Zusatzdaten je Benutzer (Login-/Passwort-Historie für die Userverwaltung).
    `last_login`/`date_joined` liefert Django selbst; hier ERSTE Anmeldung und der
    Zeitpunkt der letzten Passwortänderung."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    first_login = models.DateTimeField("Erste Anmeldung", null=True, blank=True)
    password_changed_at = models.DateTimeField("Passwort geändert", null=True, blank=True)

    def __str__(self):
        return f"Profil {self.user}"


def user_profile(user):
    """Profil eines Users holen/anlegen (idempotent)."""
    if not getattr(user, "pk", None):
        return None
    prof, _ = UserProfile.objects.get_or_create(user=user)
    return prof


def mark_password_changed(user):
    """Zeitpunkt der letzten Passwortänderung festhalten."""
    from django.utils import timezone
    prof = user_profile(user)
    if prof:
        prof.password_changed_at = timezone.now()
        prof.save(update_fields=["password_changed_at"])


class ProjectMembership(models.Model):
    """Zuordnung eines Nutzers zu einem Projekt mit einer Rolle."""
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="project_memberships")
    role = models.CharField(max_length=8, choices=Role.choices, default=Role.DESIGNER)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "user")
        ordering = ["project", "role"]

    def __str__(self):
        return f"{self.user} @ {self.project} ({self.get_role_display()})"


class EmailSettings(models.Model):
    """
    SMTP-Einstellungen, im Admin pflegbar. Überschreibt die env-Defaults aus
    settings.py (lokaler Mailserver localhost). Wird vom
    DB-E-Mail-Backend (app.email_backend) zur Laufzeit gelesen.
    """
    label = models.CharField(max_length=64, default="SMTP")
    host = models.CharField("SMTP-Host", max_length=255,
                            default="localhost")
    port = models.PositiveIntegerField("Port", default=25)
    username = models.CharField("Benutzer", max_length=255, blank=True)
    password = models.CharField("Passwort", max_length=255, blank=True)
    use_tls = models.BooleanField("STARTTLS", default=False)
    use_ssl = models.BooleanField("SSL", default=False)
    from_email = models.EmailField("Absender",
                                   default="elisa@example.com")
    timeout = models.PositiveIntegerField("Timeout (s)", default=10)
    active = models.BooleanField("aktiv", default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "E-Mail-/SMTP-Einstellung"
        verbose_name_plural = "E-Mail-/SMTP-Einstellungen"

    def __str__(self):
        return f"{self.label}: {self.host}:{self.port}"


class MCPToken(models.Model):
    """
    Bearer-Token für den MCP-Server (SSE-Transport). Verwaltung im Admin-
    Interface („Konnektivitätsverwaltung"): anlegen, deaktivieren, widerrufen.
    Der MCP-Server stellt die statischen PEP/REQ je Projekt read-only bereit.
    """
    # V-Modell-Scope: auf welcher Ebene arbeitet dieser Zugangspunkt. Bewusst nur
    # die LINKE Seite (req/spec/arch/mod) – passt zu server.py VALID_SCOPES; die
    # Teststufen sind keine Token-Scope-Dimension.
    SCOPE_CHOICES = ([("ALL", "Gesamtes V-Modell")]
                     + [(v, l) for v, l in Phase.choices if v not in TEST_PHASES])

    class Access(models.TextChoices):
        READ = "READ", "Nur lesen"
        WRITE = "WRITE", "Lesen + Status/Workflow schreiben"

    name = models.CharField(max_length=128)              # z. B. "Claude Desktop – Frömelt"
    token = models.CharField(max_length=64, unique=True, db_index=True)
    active = models.BooleanField(default=True)
    # System-Token (eingebaute Personas esra/tertius/nathan): KEINE
    # Projekt-Schranke – darf projektübergreifend arbeiten.
    system = models.BooleanField("System (projektübergreifend)", default=False)
    # Scope = WAS darf dieser Zugangspunkt:
    scope = models.CharField(max_length=5, choices=SCOPE_CHOICES, default="ALL",
                             help_text="V-Modell-Ebene; bildet sich in der URL ab (/mcp/<scope>/sse).")
    access = models.CharField(max_length=8, choices=Access.choices,
                              default=Access.READ)
    # Ein Token ist auf GENAU EIN Projekt beschränkt (Pflicht).
    project = models.ForeignKey(
        Project, null=True, blank=False, on_delete=models.CASCADE,
        related_name="mcp_tokens",
        help_text="Pflicht: Token gilt nur für dieses eine Projekt.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    @property
    def scope_slug(self) -> str:
        return self.scope.lower()

    @property
    def url_path(self) -> str:
        """Projekt + V-Modell-Scope in der URL: <projekt>/<scope>."""
        key = self.project.key if self.project_id else "kein-projekt"
        return f"{key}/{self.scope_slug}"

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({'aktiv' if self.active else 'inaktiv'})"

    @staticmethod
    def new_token() -> str:
        import secrets
        return secrets.token_urlsafe(32)


class WorkItem(models.Model):
    """Ein Knoten auf einer der vier Ebenen."""
    project = models.ForeignKey(
        Project, null=True, on_delete=models.CASCADE, related_name="work_items"
    )
    phase = models.CharField(max_length=8, choices=Phase.choices)
    identifier = models.CharField(max_length=64)  # z. B. "REQ-014" (je Projekt eindeutig)
    title = models.CharField("Überschrift", max_length=160)  # Heading (VARCHAR 160)
    body = models.TextField(blank=True)        # NUR vom Menschen geschrieben (TEXT body)
    rationale = models.TextField(blank=True)   # Begründung, prüfbar
    status = models.CharField(
        max_length=10, choices=ItemStatus.choices, default=ItemStatus.DRAFT
    )

    # Traceability nach oben (strikte V-Modell-Ableitung; Gegenrichtung refined_to)
    derived_from = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="refined_to"
    )
    # Allgemeine Kreuzreferenzen (bidirektional „back-forth", NICHT die Ableitung).
    # Symmetrisch: A ↔ B – ein Querverweis gilt in beide Richtungen.
    related = models.ManyToManyField("self", symmetrical=True, blank=True)
    # Entscheidungskette / Blocker (gerichtet): self blockiert target; Gegen-
    # richtung blocked_by (target wartet auf self). Für Abhängigkeitsketten.
    blocks = models.ManyToManyField("self", symmetrical=False, blank=True,
                                    related_name="blocked_by")
    # Verifikation (rechte V-Modell-Seite, gerichtet): ein TEST-Item verifiziert
    # ein oder mehrere Entwicklungs-Items seiner Partnerebene (siehe VERIFY_PARTNER).
    # Gegenrichtung verified_by (Entwicklungs-Item → die es prüfenden Test-Items).
    verifies = models.ManyToManyField("self", symmetrical=False, blank=True,
                                      related_name="verified_by")

    # Versionierung / Audit
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="created_items"
    )
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_items",
    )  # ab SPEC: Review durch zweite Person (≠ created_by)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="approved_items",
    )  # MUSS gesetzt sein (außer REQ), damit status == APPROVED zulässig ist
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Provenienz (für Audit). Bei Inhalt immer False -- Inhalt kommt vom Menschen.
    generated_by_llm = models.BooleanField(default=False)
    llm_model = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["identifier"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "identifier"], name="uniq_identifier_per_project"
            )
        ]
        permissions = [
            ("approve_workitem", "Darf WorkItems freigeben (Status APPROVED)"),
            ("audit_workitem", "Darf WorkItems per Audit ZURÜCKSTUFEN (eine Stufe)"),
        ]

    def __str__(self):
        return f"{self.identifier} [{self.get_phase_display()}]"

    @property
    def is_orphan(self):
        """Lücke in der Traceability. Links: ein abgeleitetes Item ohne Verbindung
        nach oben (`derived_from`). Rechts: ein Test-Item, das nichts verifiziert
        (`verifies`)."""
        if self.phase in TEST_PHASES:
            return not self.verifies.exists()
        return self.phase != Phase.REQUIREMENT and not self.derived_from.exists()

    @property
    def is_unverified(self):
        """Entwicklungs-Item (linke Seite) ohne ein verifizierendes Test-Item →
        Lücke in der V-Modell-Abdeckung der rechten Seite. REQ zählt mit."""
        return self.phase not in TEST_PHASES and not self.verified_by.exists()

    def save(self, *args, **kwargs):
        # Harte Invariante: APPROVED nur mit menschlichem approved_by – AUSSER bei
        # REQ: Anforderungen spiegeln das signierte Kundendokument (extern frei-
        # gegeben), sie sind per Default APPROVED ohne internen approved_by.
        if (self.status == ItemStatus.APPROVED and self.approved_by_id is None
                and self.phase != Phase.REQUIREMENT):
            raise ValueError("APPROVED erfordert einen menschlichen approved_by.")
        super().save(*args, **kwargs)


class NormClause(models.Model):
    """Eine Klausel/ein Abschnitt aus einer Norm (z. B. '6.4.1')."""
    standard = models.CharField(max_length=64)        # z. B. "IEC 61508-3"
    clause = models.CharField(max_length=64)          # z. B. "6.4.1"
    text = models.TextField()
    source_page = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("standard", "clause")

    def __str__(self):
        return f"{self.standard} {self.clause}"


class NormLink(models.Model):
    """
    Verknüpft ein WorkItem mit der Norm-Klausel, die es adressiert.
    Vom RAG vorgeschlagen, vom Menschen bestätigt (confirmed).
    """
    item = models.ForeignKey(WorkItem, on_delete=models.CASCADE, related_name="norm_links")
    clause = models.ForeignKey(NormClause, on_delete=models.PROTECT)
    confidence = models.FloatField(null=True, blank=True)  # Retrieval-Score
    confirmed = models.BooleanField(default=False)         # menschliche Bestätigung

    class Meta:
        unique_together = ("item", "clause")


# ── Beratungs-Chat (CLAUDE.md, Regel 3, dritte Kategorie) ──────────────────
#
# WICHTIG / Guardrails:
#   - Dies ist ein BERATENDER, persistierter Chat. Er ist NIE Quelle der
#     Wahrheit. Kein Endpoint schreibt aus dem Chat heraus in WorkItem.body
#     oder ein anderes verbindliches Feld. Übernahme in eine Spezifikation
#     ist immer manuelles, menschliches Einfügen.
#   - Antworten des Assistenten werden mit Provenienz geführt
#     (role=ASSISTANT, llm_model) und bleiben damit auditierbar.
#   - Der Chat ist RAG-gestützt: passende Norm-Klauseln werden abgerufen und
#     dem LLM als Kontext beigelegt; verwendete Klauseln werden referenziert.

class ChatRole(models.TextChoices):
    USER = "USER", "Mensch"
    ASSISTANT = "ASSISTANT", "Assistent (LLM)"
    SYSTEM = "SYSTEM", "System"


class ChatSession(models.Model):
    """Ein Gesprächsfaden (wie eine Konversation in Claude Desktop)."""
    project = models.ForeignKey(
        Project, null=True, on_delete=models.CASCADE, related_name="chat_sessions"
    )
    title = models.CharField(max_length=255, blank=True)
    owner = models.ForeignKey(
        User, null=True, on_delete=models.CASCADE, related_name="chat_sessions"
    )
    # Optionaler fachlicher Bezug — rein als Kontext, nicht verbindlich.
    related_item = models.ForeignKey(
        WorkItem, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="chat_sessions",
    )
    # Projekt-Chat: geteilter Faden für ALLE Projektmitglieder (kein owner,
    # kein Item). Jedes Projekt hat per Default einen; Admin/PM legen weitere an.
    shared = models.BooleanField("Projekt-Chat (geteilt)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Chat #{self.pk}"


class ChatMessage(models.Model):
    """
    Eine Nachricht im Beratungs-Chat. Beratend & persistiert, aber nie
    Quelle der Wahrheit (siehe Guardrails oben).
    """
    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=10, choices=ChatRole.choices)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    # Absender: Mensch (author) ODER externer/LLM-Absender (author_label, z. B.
    # der @-Handle des antwortenden LLM). Ersetzt das generische „Mensch".
    author = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="chat_messages")
    author_label = models.CharField(max_length=64, blank=True)
    # Bezug: auf welche Nachricht diese Antwort antwortet (sichtbar im Chat).
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="replies")

    # Provenienz (Audit). Bei ASSISTANT immer True.
    generated_by_llm = models.BooleanField(default=False)
    llm_model = models.CharField(max_length=64, blank=True)
    # Welche Norm-Klauseln das RAG für diese Antwort beigesteuert hat.
    cited_clauses = models.ManyToManyField(NormClause, blank=True,
                                           related_name="chat_citations")
    # Zitierte Norm-Quellen (pgvector-RAG): [{"quelle": <datei>, "seite": <n>}].
    cited_sources = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:40]}"

    def sender_label(self) -> str:
        """Konkreter Absender statt generischem „Mensch"."""
        if self.author_id:
            return self.author.get_full_name() or self.author.get_username()
        if self.author_label:
            return self.author_label
        if self.role == ChatRole.ASSISTANT:
            return self.llm_model or "LLM"
        if self.role == ChatRole.SYSTEM:
            return "System"
        return "Mensch"

    @property
    def is_human(self) -> bool:
        return self.role == ChatRole.USER


class LifecycleEvent(models.Model):
    """
    Revisions-/Iterationshistorie des iterativen Zyklus (Nachweis nach IEC 61508).
    Hängt entweder an einem WorkItem oder an einem ProjectDocument.
    """
    work_item = models.ForeignKey(
        WorkItem, null=True, blank=True, on_delete=models.CASCADE,
        related_name="lifecycle_events")
    document = models.ForeignKey(
        ProjectDocument, null=True, blank=True, on_delete=models.CASCADE,
        related_name="lifecycle_events")
    from_state = models.CharField(max_length=10, choices=ItemStatus.choices, blank=True)
    to_state = models.CharField(max_length=10, choices=ItemStatus.choices)
    iteration = models.PositiveIntegerField(default=1)
    by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL,
                           related_name="lifecycle_events")
    at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-at"]

    def __str__(self):
        target = self.work_item or self.document
        return f"{target}: {self.from_state}→{self.to_state} (it.{self.iteration})"


class FeedbackStatus(models.TextChoices):
    PENDING = "PENDING", "offen"
    CLAIMED = "CLAIMED", "in Bearbeitung"
    ANSWERED = "ANSWERED", "beantwortet"


class FeedbackRequest(models.Model):
    """
    Anfrage für Write-time-Toasts. Wird vom Editor angelegt; das MCP-Team
    (starke LLMs) holt sie per Tool, analysiert und liefert das Toast-JSON
    zurück. Notnagel: Ollama, wenn kein Team verbunden ist.

    Es wird NIE Inhalt geschrieben – nur Toasts (CLAUDE.md, Toast-Vertrag).
    """
    project = models.ForeignKey(Project, null=True, on_delete=models.CASCADE,
                                related_name="feedback_requests")
    item = models.ForeignKey(WorkItem, null=True, blank=True,
                             on_delete=models.SET_NULL,
                             related_name="feedback_requests")
    draft = models.TextField()
    neighbours = models.JSONField(default=list)          # [{"id":.., "body":..}]
    status = models.CharField(max_length=10, choices=FeedbackStatus.choices,
                              default=FeedbackStatus.PENDING)
    toasts = models.JSONField(default=list)              # gefüllt vom Team/Ollama
    source = models.CharField(max_length=16, blank=True)  # "team" | "ollama"
    answered_by = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Feedback #{self.pk} ({self.status})"


class WorkerBackend(models.Model):
    """
    Verwaltbares Inferenz-Backend für den Persona-Worker (poll-freie Toasts).

    Anthropic (Claude) spricht das Anthropic-Protokoll; alle anderen Anbieter
    (OpenAI/ChatGPT, DeepSeek, Ollama, LM Studio, beliebige OpenAI-kompatible)
    nutzen dasselbe OpenAI-Protokoll und unterscheiden sich nur in
    Base-URL/Key/Modell. Ein Backend ist über einen MCP-Token an genau EIN
    Projekt + V-Schritt (Scope) gebunden – daraus ergibt sich, welche
    Feedback-Warteschlange es bedient.
    """
    class Provider(models.TextChoices):
        CLAUDE = "CLAUDE", "Anthropic Claude"
        OPENAI = "OPENAI", "OpenAI / ChatGPT"
        DEEPSEEK = "DEEPSEEK", "DeepSeek"
        OLLAMA = "OLLAMA", "Ollama (lokal)"
        LMSTUDIO = "LMSTUDIO", "LM Studio (lokal)"
        ELIEZER = "ELIEZER", "Eliezer (lokal)"
        CUSTOM = "CUSTOM", "OpenAI-kompatibel (custom)"

    # (Protokoll, Default-Base-URL, Default-Modell) je Anbieter.
    PROVIDER_DEFAULTS = {
        "CLAUDE":   ("claude", "",                            "claude-haiku-4-5"),
        "OPENAI":   ("openai", "https://api.openai.com/v1",   "gpt-4o-mini"),
        "DEEPSEEK": ("openai", "https://api.deepseek.com/v1", "deepseek-chat"),
        "OLLAMA":   ("openai", "http://127.0.0.1:11434/v1",   "llama3.1"),
        "LMSTUDIO": ("openai", "http://localhost:1234/v1",    "local-model"),
        "ELIEZER":  ("openai", "http://127.0.0.1:1234/v1",    ""),
        "CUSTOM":   ("openai", "",                            ""),
    }

    name = models.CharField(max_length=64, unique=True,
                            help_text="Eindeutiger Name, z. B. „Claude REQ“ oder „LMStudio zuhause“.")
    provider = models.CharField(max_length=10, choices=Provider.choices,
                                default=Provider.CLAUDE)
    model = models.CharField(max_length=128, blank=True,
                             help_text="Leer = Anbieter-Default (z. B. claude-haiku-4-5).")
    base_url = models.CharField("Base-URL", max_length=255, blank=True,
                                help_text="Leer = Anbieter-Default. Für Ollama/LM Studio/Eliezer/DeepSeek/custom.")
    api_key = models.CharField("API-Key", max_length=255, blank=True,
                               help_text="Geheim. Claude: ANTHROPIC-Key. Eliezer: sk-… aus `eliezer --new-key`. Ollama/LM Studio: beliebig.")
    token = models.ForeignKey(MCPToken, on_delete=models.PROTECT,
                              related_name="worker_backends",
                              help_text="WRITE-Token → bindet Projekt + V-Schritt (Scope).")
    mcp_base = models.CharField("MCP-Basis-URL", max_length=255, blank=True,
                                help_text="Leer = MCP_PUBLIC_BASE bzw. http://127.0.0.1:8765.")
    active = models.BooleanField(default=True)
    # Freier @-Handle im Chat (z. B. "esra"); leer = aus dem Provider abgeleitet.
    handle = models.CharField(max_length=32, blank=True,
                              help_text="@-Handle im Chat (leer = aus Provider abgeleitet).")
    # Fester Endpunkt (z. B. Esra/Normenrecherche): im Admin nicht löschbar.
    protected = models.BooleanField("Geschützt (nicht löschbar)", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_provider_display()})"

    @property
    def protocol(self) -> str:
        return self.PROVIDER_DEFAULTS.get(self.provider, ("openai", "", ""))[0]

    @property
    def effective_handle(self) -> str:
        from app.participants import _PROVIDER_HANDLE
        return (self.handle or "").strip() or _PROVIDER_HANDLE.get(self.provider, "llm")

    @property
    def effective_base_url(self) -> str:
        """Leer = Anbieter-Default; Eliezer/Ollama folgen der konfigurierten
        Umgebung (im Container zeigt 127.0.0.1 sonst auf den Container selbst)."""
        if self.base_url:
            return self.base_url
        from django.conf import settings
        if self.provider == "ELIEZER":
            return settings.ELIEZER_BASE_URL.rstrip("/") + "/v1"
        if self.provider == "OLLAMA":
            return settings.OLLAMA_HOST.rstrip("/") + "/v1"
        return self.PROVIDER_DEFAULTS.get(self.provider, ("", "", ""))[1]

    @property
    def effective_api_key(self) -> str:
        """Eigener Key, sonst der Eliezer-Key aus der Umgebung (nie im Repo)."""
        if self.api_key:
            return self.api_key
        if self.provider == "ELIEZER":
            from django.conf import settings
            return settings.ELIEZER_API_KEY
        return ""

    @property
    def effective_model(self) -> str:
        return self.model or self.PROVIDER_DEFAULTS.get(self.provider, ("", "", ""))[2]

    @property
    def effective_mcp_base(self) -> str:
        import os
        # On-Box-Worker spricht den MCP über Loopback an (die öffentliche
        # nginx-URL löst auf dem Server nicht auf). Remote/Home-Worker setzen
        # mcp_base explizit auf https://<host>/mcp.
        return self.mcp_base or os.getenv("MCP_INTERNAL_BASE", "http://127.0.0.1:8765")


class WorkItemHistory(models.Model):
    """
    Lückenlose, append-only Inhalts-Historie eines WorkItems (Nachweis nach
    IEC 61508): JEDE Änderung an einem nachverfolgten Feld wird mit Person, Zeit
    und alt→neu festgehalten – jederzeit durch jede Person rückverfolgbar.
    Status-Übergänge stehen in [LifecycleEvent]; beide ergeben zusammen die
    vollständige Item-Historie. Wird nie verändert oder gelöscht.
    """
    class Kind(models.TextChoices):
        CREATED = "CREATED", "angelegt"
        EDITED = "EDITED", "Feld bearbeitet"
        STATUS = "STATUS", "Status geändert"
        TRACE = "TRACE", "Verknüpfung geändert"

    item = models.ForeignKey(WorkItem, on_delete=models.CASCADE,
                             related_name="history")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    field = models.CharField(max_length=32, blank=True)     # bei EDITED
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL,
                           related_name="item_changes")
    at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)
    # Bindung an den Item-Chat: Änderungen sollen über den Chat begründet werden.
    chat_message = models.ForeignKey(ChatMessage, null=True, blank=True,
                                     on_delete=models.SET_NULL,
                                     related_name="item_changes")

    class Meta:
        ordering = ["-at"]
        verbose_name = "WorkItem-Historie"
        verbose_name_plural = "WorkItem-Historie"

    def __str__(self):
        who = self.by.get_username() if self.by_id else "—"
        return f"{self.item.identifier} {self.get_kind_display()} ({who})"


class EmbeddingChunk(models.Model):
    """
    Vektor-Index in Postgres (pgvector) – löst ChromaDB ab. Ein Chunk = ein
    Textstück eines Norm- oder Projektdokuments mit Embedding (nomic-embed-text,
    768 Dim). `collection` trennt die Räume: „normen" (global) bzw. „proj-<key>".
    Quelle der Wahrheit bleibt die DB; Embeddings sind reine Mechanik.
    """
    EMBED_DIM = 768

    collection = models.CharField(max_length=64, db_index=True)   # "normen" | "proj-<key>"
    project = models.ForeignKey(Project, null=True, blank=True,
                                on_delete=models.CASCADE, related_name="embedding_chunks")
    source = models.CharField(max_length=255)                     # Dateiname (quelle)
    page = models.PositiveIntegerField(null=True, blank=True)     # seite
    kind = models.CharField(max_length=16, blank=True)
    text = models.TextField()
    uid = models.CharField(max_length=64, unique=True)            # md5 → Upsert (je Chunk)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)  # SHA-256 der Datei
    embedding = VectorField(dimensions=EMBED_DIM)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["collection", "source"]),
            HnswIndex(name="embchunk_hnsw", fields=["embedding"],
                      m=16, ef_construction=64, opclasses=["vector_cosine_ops"]),
        ]

    def __str__(self):
        return f"{self.collection}/{self.source} S.{self.page}"


class Keyword(models.Model):
    """
    Schlagwort im Katalog. Vom GROSSEN LLM (MCP) vorgeschlagen, vom Menschen
    bestätigt. Bildet zusammen mit der Volltextsuche (Postgres FTS) und den
    Embeddings (pgvector) die Dokumentensuche; das kleine Ollama erdet seine
    Suche daran (nur Retrieval, nie verbindlich).
    """
    text = models.SlugField(max_length=80, unique=True,
                            help_text="Normalisiertes Schlagwort (klein, ohne Leerzeichen).")
    label = models.CharField(max_length=120, blank=True, help_text="Anzeigeform.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["text"]
        verbose_name = "Schlagwort"
        verbose_name_plural = "Schlagwortkatalog"

    def __str__(self):
        return self.label or self.text


class KeywordLink(models.Model):
    """
    Verknüpfung Schlagwort ↔ WorkItem oder Dokument – mit Provenienz und
    menschlicher Bestätigung (CLAUDE.md Regel 1/3: LLM schlägt vor `confirmed=False`,
    ein Mensch bestätigt). Wie `NormLink`, nur für Schlagwörter.
    """
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name="links")
    work_item = models.ForeignKey(WorkItem, null=True, blank=True,
                                  on_delete=models.CASCADE, related_name="keyword_links")
    document = models.ForeignKey(ProjectDocument, null=True, blank=True,
                                 on_delete=models.CASCADE, related_name="keyword_links")
    # Schlagwort je RAG-CHUNK – feinkörnig (jeder Chunk braucht mehrere). So wächst
    # der Katalog auf hunderte Einträge; Keyword.text bleibt UNIQUE.
    chunk = models.ForeignKey("EmbeddingChunk", null=True, blank=True,
                              on_delete=models.CASCADE, related_name="keyword_links")
    confidence = models.FloatField(null=True, blank=True)        # LLM-Score
    generated_by_llm = models.BooleanField(default=False)
    llm_model = models.CharField(max_length=64, blank=True)
    confirmed = models.BooleanField(default=False)               # menschliche Bestätigung
    confirmed_by = models.ForeignKey(User, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="confirmed_keywords")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-confidence"]
        # Bedingte Unique-Constraints: nullbare FKs lassen sonst Duplikate zu
        # (NULL ≠ NULL in Postgres). So ist je Ziel das Keyword GENAU einmal
        # verknüpft; das Keyword-Vokabular selbst ist über Keyword.text unique.
        constraints = [
            models.UniqueConstraint(fields=["keyword", "work_item"],
                                    condition=models.Q(work_item__isnull=False),
                                    name="uniq_keyword_per_item"),
            models.UniqueConstraint(fields=["keyword", "document"],
                                    condition=models.Q(document__isnull=False),
                                    name="uniq_keyword_per_document"),
            models.UniqueConstraint(fields=["keyword", "chunk"],
                                    condition=models.Q(chunk__isnull=False),
                                    name="uniq_keyword_per_chunk"),
        ]

    def __str__(self):
        target = self.work_item.identifier if self.work_item_id else (
            str(self.document) if self.document_id else "—")
        return f"{self.keyword} → {target}"


class EsraTask(models.Model):
    """EVENT-GETRIEBENE Aufgabe für die Esra-Persona (Normenrecherche).
    Wird angelegt bei jedem UPLOAD (Dokument indiziert → Chunks verschlagworten)
    und jedem GENERATE (Item erzeugt → Item-Text gegen den Schlagwortkatalog
    abgleichen und passende Normen finden). Der Esra-Worker holt PENDING-Tasks,
    erledigt sie agentisch und setzt sie auf DONE/ERROR."""
    class Kind(models.TextChoices):
        TAG_DOCUMENT = "TAG_DOC", "Dokument verschlagworten"
        TAG_NORM = "TAG_NORM", "Norm verschlagworten"
        MATCH_ITEM = "MATCH_ITEM", "Item ↔ Normen abgleichen"

    class Status(models.TextChoices):
        PENDING = "PENDING", "offen"
        RUNNING = "RUNNING", "läuft"
        DONE = "DONE", "erledigt"
        ERROR = "ERROR", "Fehler"

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="esra_tasks")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    document = models.ForeignKey(ProjectDocument, null=True, blank=True,
                                 on_delete=models.CASCADE)
    work_item = models.ForeignKey(WorkItem, null=True, blank=True,
                                  on_delete=models.CASCADE)
    ref = models.CharField(max_length=255, blank=True)   # z. B. Norm-Quelle/Offset
    status = models.CharField(max_length=8, choices=Status.choices,
                              default=Status.PENDING, db_index=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Esra[{self.get_kind_display()}] {self.project.key} ({self.status})"


def enqueue_esra(project, kind, *, document=None, work_item=None, ref=""):
    """Legt eine PENDING-Esra-Aufgabe an (idempotent je offenem Ziel). Nur wenn
    der Esra-Endpunkt aktiv ist – sonst kein Sinn."""
    if project is None:
        return None
    if not WorkerBackend.objects.filter(handle="esra", active=True).exists():
        return None
    existing = EsraTask.objects.filter(
        project=project, kind=kind, document=document, work_item=work_item,
        ref=ref, status=EsraTask.Status.PENDING).first()
    if existing:
        return existing
    return EsraTask.objects.create(
        project=project, kind=kind, document=document, work_item=work_item, ref=ref)


class ItemTranslation(models.Model):
    """ASYNC-Übersetzung eines Items in eine Sekundärsprache (informativ, nie
    normativ). Der „Übersetzen"-Button legt sie PENDING an; ein Hintergrund-Thread
    (Tertius-LLM) füllt sie; die UI pollt bis DONE. Pro Item+Sprache eine."""
    class Status(models.TextChoices):
        PENDING = "PENDING", "offen"
        RUNNING = "RUNNING", "läuft"
        DONE = "DONE", "fertig"
        ERROR = "ERROR", "Fehler"

    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE,
                                  related_name="translations")
    lang = models.CharField(max_length=8)
    status = models.CharField(max_length=8, choices=Status.choices,
                              default=Status.PENDING)
    text = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["work_item", "lang"],
                                               name="uniq_item_lang_translation")]

    def __str__(self):
        return f"Übersetzung {self.work_item_id}/{self.lang} ({self.status})"


class EmbeddedImage(models.Model):
    """Abbildung oder Tabelle eines WorkItems – am DOKUMENT-ENDE gesammelt (Anhang),
    nummeriert (z. B. „Figure 3") und im Text nur per Nummer referenziert. Bilder
    als base64-`data` (kein Body-Aufblähen); Urheber-/Quellenangabe optional."""
    class Kind(models.TextChoices):
        FIGURE = "FIGURE", "Abbildung"
        TABLE = "TABLE", "Tabelle"

    work_item = models.ForeignKey(WorkItem, on_delete=models.CASCADE,
                                  related_name="exhibits")
    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.FIGURE)
    number = models.PositiveIntegerField(default=1)         # 3 → „Figure 3"
    caption = models.CharField(max_length=255, blank=True)
    mime = models.CharField(max_length=40, default="image/png")
    data = models.TextField("base64-Bilddaten", blank=True)  # für Abbildungen
    table_html = models.TextField("Tabellen-HTML/Markdown", blank=True)  # für Tabellen
    attribution = models.CharField("Urheber / Quelle / ©", max_length=255, blank=True)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "number", "id"]

    def __str__(self):
        return f"{self.label} ({self.work_item.identifier})"

    @property
    def label(self):
        kind = "Abbildung" if self.kind == self.Kind.FIGURE else "Tabelle"
        return f"{kind} {self.number}"

    @property
    def data_uri(self):
        d = (self.data or "").strip()
        if not d:
            return ""
        return d if d.startswith("data:") else f"data:{self.mime};base64,{d}"
