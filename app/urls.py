from django.urls import path
from django.views.generic.base import RedirectView

from . import (views, views_feedback, views_chat, views_norms,
               views_projects, views_customers, views_docmgmt, views_users)

urlpatterns = [
    # Eigenes Profil (Selbstbedienung)
    path("profile/", views_users.profile, name="profile"),
    # User management + roles/team
    path("users/", views_users.user_list, name="users"),
    path("users/new/", views_users.user_create, name="user-create"),
    path("users/<int:pk>/edit/", views_users.user_edit, name="user-edit"),
    path("users/<int:pk>/toggle/", views_users.user_toggle, name="user-toggle"),
    path("users/<int:pk>/password/", views_users.user_set_password, name="user-set-password"),
    path("users/<int:pk>/delete/", views_users.user_delete, name="user-delete"),
    # Old /benutzer/ -> /users/ (bookmarks)
    path("benutzer/", RedirectView.as_view(pattern_name="users", permanent=True)),
    path("team/", views_users.team, name="team"),
    path("team/add/", views_users.team_add, name="team-add"),
    path("team/<int:pk>/rolle/", views_users.team_update, name="team-update"),
    path("team/<int:pk>/entfernen/", views_users.team_remove, name="team-remove"),

    # Kundenverwaltung
    path("kunden/", views_customers.customer_list, name="customers"),
    path("kunden/neu/", views_customers.customer_form, name="customer-create"),
    path("kunden/<int:pk>/", views_customers.customer_form, name="customer-edit"),
    path("kunden/<int:pk>/archivieren/", views_customers.customer_archive, name="customer-archive"),
    path("kunden/<int:pk>/loeschen/", views_customers.customer_delete, name="customer-delete"),

    # Projektverwaltung (Mandanten) — volles CRUD
    path("projekte/", views_projects.project_list, name="projects"),
    path("projekte/neu/", views_projects.project_create, name="project-create"),
    path("projekte/formular/", views_projects.project_form, name="project-form"),
    path("projekte/<int:pk>/bearbeiten/", views_projects.project_form, name="project-edit"),
    path("projekte/<int:pk>/wechseln/", views_projects.project_switch, name="project-switch"),
    path("projekte/<int:pk>/archivieren/", views_projects.project_archive, name="project-archive"),
    path("projekte/<int:pk>/loeschen/", views_projects.project_delete, name="project-delete"),
    path("projekte/<int:pk>/language/add/", views_projects.project_lang_add, name="project-lang-add"),
    path("projekte/<int:pk>/language/remove/", views_projects.project_lang_remove, name="project-lang-remove"),
    path("projekte/<int:pk>/language/mode/", views_projects.project_lang_mode, name="project-lang-mode"),
    path("set-language/", views_projects.set_language, name="set-language"),

    # Eingangsdokumente (DMS je Projekt)
    path("inputs/", views_docmgmt.doc_list, name="docmgmt"),
    path("inputs/upload/", views_docmgmt.doc_upload, name="doc-upload"),
    path("inputs/<int:pk>/download/", views_docmgmt.doc_download, name="doc-download"),
    path("inputs/<int:pk>/delete/", views_docmgmt.doc_delete, name="doc-delete"),
    path("inputs/<int:pk>/status/", views_docmgmt.doc_transition, name="doc-transition"),
    # Alt-URL /eingaenge/ -> /inputs/ (Bookmarks)
    path("eingaenge/", RedirectView.as_view(pattern_name="docmgmt", permanent=True)),

    # Tabs
    path("", views.home, name="home"),
    path("workspace/", views.workspace, name="workspace"),
    path("workspace/<str:identifier>/text/", views.workitem_text, name="workitem-text"),
    path("workspace/add/", views.workitem_add, name="workitem-add"),
    path("workspace/<str:identifier>/editor/", views.workitem_editor, name="workitem-editor"),
    path("workspace/<str:identifier>/revision/delete/", views.workitem_revision_delete, name="workitem-revision-delete"),
    path("workspace/<str:identifier>/chat/", views.workitem_chat_pane, name="workitem-chat-pane"),
    path("workspace/<str:identifier>/status/", views.workitem_status, name="workitem-status"),
    path("workspace/<str:identifier>/ref/", views.workitem_ref, name="workitem-ref"),
    path("workspace/<str:identifier>/translate/", views.workitem_translate, name="workitem-translate"),
    path("workspace/<str:identifier>/translate/poll/", views.workitem_translation_poll, name="workitem-translation-poll"),
    path("workspace/<str:identifier>/audit/", views.workitem_audit, name="workitem-audit"),
    path("api/online/", views.online_presence, name="online-presence"),
    path("documents/", views.documents, name="documents"),
    path("documents/<str:phase>/generate/", views.generate_document,
         name="generate-document"),

    # Normen (Upload + RAG-Index)
    path("normen/", views_norms.norms_index, name="norms"),
    path("normen/progress/", views_norms.norms_progress, name="norms-progress"),
    path("normen/upload/", views_norms.norms_upload, name="norms-upload"),
    path("normen/build/", views_norms.norms_build, name="norms-build"),
    path("normen/reindex/", views_norms.norms_reindex, name="norms-reindex"),
    path("normen/forget/", views_norms.norms_forget, name="norms-forget"),
    path("normen/rename/", views_norms.norms_rename, name="norms-rename"),
    path("normen/classify/", views_norms.norms_classify, name="norms-classify"),
    path("normen/download/", views_norms.norms_download, name="norms-download"),

    # Chat (beratend, persistiert, RAG-gestützt)
    path("chat/", views_chat.chat_index, name="chat"),
    path("chat/new/", views_chat.chat_new, name="chat-new"),
    path("chat/new-project/", views_chat.chat_new_project, name="chat-new-project"),
    path("chat/<int:pk>/", views_chat.chat_session, name="chat-session"),
    path("chat/<int:pk>/send/", views_chat.chat_send, name="chat-send"),
    path("chat/<int:pk>/poll/", views_chat.chat_poll, name="chat-poll"),
    path("chat/<int:pk>/delete/", views_chat.chat_delete, name="chat-delete"),
    path("chat/message/<int:pk>/delete/", views_chat.chat_message_delete,
         name="chat-message-delete"),
    path("chat/<int:pk>/rename/", views_chat.chat_rename, name="chat-rename"),

    # Beratendes Live-Feedback (Editor)
    path("api/writing-feedback/", views_feedback.writing_feedback,
         name="writing-feedback"),
    path("api/feedback-poll/", views_feedback.feedback_poll, name="feedback-poll"),
    path("api/toast-action/", views_feedback.toast_action, name="toast-action"),
]
