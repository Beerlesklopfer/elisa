"""Formulare. CustomerForm deckt die vollen internationalen Kundenattribute ab."""
from django import forms

from .models import Customer, Project, EmailSettings


class EmailSettingsForm(forms.ModelForm):
    """SMTP-Konfiguration im Admin – Auth wird hier gepflegt, nicht angenommen."""
    class Meta:
        model = EmailSettings
        fields = "__all__"
        widgets = {
            "password": forms.PasswordInput(render_value=True),
        }
        help_texts = {
            "username": "Leer lassen = OHNE Authentifizierung (offener Relay).",
            "password": "Nur nötig, wenn der Mailserver Authentifizierung verlangt.",
            "use_tls": "STARTTLS (z. B. Port 587). Schließt SSL aus.",
            "use_ssl": "SSL/TLS direkt (z. B. Port 465). Schließt STARTTLS aus.",
            "host": "SMTP-Server (Hostname oder IP).",
            "port": "25 (unverschlüsselt), 587 (STARTTLS) oder 465 (SSL).",
        }

    def clean(self):
        data = super().clean()
        if data.get("use_tls") and data.get("use_ssl"):
            raise forms.ValidationError("STARTTLS und SSL schließen sich aus – nur eines wählen.")
        # Auth: entweder beide leer (kein Auth) oder beide gesetzt.
        u, p = data.get("username"), data.get("password")
        if bool(u) ^ bool(p):
            raise forms.ValidationError(
                "Für Authentifizierung Benutzer UND Passwort angeben (oder beides leer für offenen Relay).")
        return data


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "customer", "key", "description"]
        labels = {
            "name": "Projektname",
            "customer": "Kunde",
            "key": "Kürzel / Projektnummer",
            "description": "Beschreibung",
        }
        help_texts = {
            "key": "Eindeutiges Kürzel, z. B. sa2026-1345. Leer = automatisch.",
            "customer": "Zugeordneter Kunde (optional).",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["key"].required = False
        self.fields["customer"].queryset = Customer.objects.filter(archived=False)
        self.fields["customer"].required = False
        for field in self.fields.values():
            widget = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.setdefault("class", widget)


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "number", "name", "legal_form",
            "address_line1", "address_line2", "postal_code", "city",
            "region", "country",
            "vat_id", "registration_no",
            "contact_person", "contact_email", "phone", "website",
            "language", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "number": "Kundennummer",
            "name": "Firma / Organisation",
            "legal_form": "Rechtsform",
            "address_line1": "Straße / Adresszeile 1",
            "address_line2": "Adresszeile 2",
            "postal_code": "PLZ / ZIP",
            "city": "Stadt",
            "region": "Region / Bundesland / State",
            "country": "Land",
            "vat_id": "USt-IdNr. / VAT / Tax ID",
            "registration_no": "Handelsregister / Reg.-Nr.",
            "contact_person": "Ansprechpartner",
            "contact_email": "E-Mail",
            "phone": "Telefon",
            "website": "Webseite",
            "language": "Sprache",
            "notes": "Notizen",
        }
        help_texts = {
            "number": "Eindeutige Kundennummer. Leer lassen = automatisch generieren.",
            "name": "Offizieller Firmen-/Organisationsname.",
            "legal_form": "z. B. GmbH, AG, Ltd., Inc., S.A., S.r.l.",
            "address_line1": "Straße und Hausnummer.",
            "address_line2": "Zusatz (Gebäude, Etage, c/o) – optional.",
            "postal_code": "Postleitzahl / ZIP / Postal Code.",
            "city": "Ort / Stadt.",
            "region": "Bundesland, Kanton, Provinz oder State – je nach Land.",
            "country": "ISO-3166-Ländercode, z. B. DE, US, CN, CH.",
            "vat_id": "Umsatzsteuer-ID / VAT / Tax ID, z. B. DE123456789.",
            "registration_no": "Handelsregister-/Company-Registration-Nummer.",
            "contact_person": "Primärer Ansprechpartner beim Kunden.",
            "contact_email": "E-Mail-Adresse des Ansprechpartners.",
            "phone": "Telefon im internationalen Format, z. B. +49 5222 123456.",
            "website": "Webseite inkl. https://",
            "language": "Bevorzugte Sprache (ISO 639), z. B. de, en, fr.",
            "notes": "Freitext / interne Hinweise.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Bootstrap-Styling + number optional (wird sonst generiert).
        self.fields["number"].required = False
        for name, field in self.fields.items():
            css = "form-check-input" if isinstance(field.widget, forms.CheckboxInput) else "form-control"
            field.widget.attrs.setdefault("class", css)
