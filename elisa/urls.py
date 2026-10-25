"""
Top-Level-URLs für ELISA.

Die Tabs der Oberfläche:
  - Editor    (Spezifikation schreiben, mit beratendem Live-Feedback)
  - Chat      (RAG-gestützte Norm-Beratung, beratend & persistiert, nie Quelle der Wahrheit)
  - Dokumente (WorkItem → Markdown → Word im ELISA-Design)
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

from app.views_auth import DBLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    # Login mit DB-/Mandanten-Auswahl (ERP-Stil) – MUSS vor auth.urls stehen.
    path("accounts/login/", DBLoginView.as_view(), name="login"),
    # Logout, Passwort ändern UND Passwort vergessen/zurücksetzen.
    # (django.contrib.auth.urls nutzt die Templates unter registration/.)
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("app.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
