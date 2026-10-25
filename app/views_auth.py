"""
Login mit DB-/Mandanten-Auswahl (ERP-Stil).

Das Formular bekommt ein zusätzliches Feld „database". Dessen Wert wird VOR der
Authentifizierung im Router-Thread-local gesetzt, damit `authenticate()` gegen
die gewählte DB läuft. Nach erfolgreichem Login wird der Alias in der Session
gespeichert (die liegt in 'default') und steuert ab dann jeden Request.
"""
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django import forms

from app import dbrouter


def _choices():
    return list(getattr(settings, "SELECTABLE_DATABASES", [("default", "Standard")]))


class DBAuthenticationForm(AuthenticationForm):
    database = forms.ChoiceField(label="Datenbank", required=True)

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["database"].choices = _choices()

    def clean(self):
        valid = {a for a, _ in _choices()}
        alias = self.data.get("database", "default")
        if alias not in valid:
            alias = "default"
        self.chosen_db = alias
        # Authentifizierung (in super().clean()) gegen die gewählte DB routen.
        dbrouter.set_db(alias)
        try:
            return super().clean()
        finally:
            pass  # Reset macht die Middleware am Request-Ende.


class DBLoginView(LoginView):
    authentication_form = DBAuthenticationForm

    def form_valid(self, form):
        response = super().form_valid(form)        # login(request, user)
        self.request.session["db"] = getattr(form, "chosen_db", "default")
        return response
