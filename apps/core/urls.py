from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("anmelden/", views.login_view, name="login"),
    path("abmelden/", views.logout_view, name="logout"),
    path("healthz", views.healthz, name="healthz"),
    path("speculation-rules.json", views.speculation_rules, name="speculation_rules"),
    path("favicon.ico", RedirectView.as_view(url="/static/img/favicon.svg", permanent=True)),
    path("medien/<path:path>", views.media, name="media"),
    path("kalender/", views.calendar_view, name="calendar"),
    path("suche/", views.search, name="search"),
    path("profil/", views.profile, name="profile"),
    path("einstellungen/", views.settings_company, name="settings"),
    path("einstellungen/steuer-bank/", views.settings_tax, name="settings_tax"),
    path("einstellungen/regeln/", views.settings_rules, name="settings_rules"),
    path("einstellungen/email/", views.settings_mail, name="settings_mail"),
    path("einstellungen/webdav/", views.settings_webdav, name="settings_webdav"),
    path("einstellungen/drucker/", views.settings_printer, name="settings_printer"),
    path("einstellungen/vorlagen/", views.settings_templates, name="settings_templates"),
    path("einstellungen/vorlagen/<str:key>/", views.settings_template_edit, name="settings_template_edit"),
    path("einstellungen/benutzer/", views.users_list, name="users"),
    path("einstellungen/benutzer/neu/", views.user_edit, name="user_create"),
    path("einstellungen/benutzer/<int:pk>/", views.user_edit, name="user_edit"),
    path("einstellungen/protokoll/", views.activity_log, name="activity"),
    path("einstellungen/backups/", views.backups, name="backups"),
    path("einstellungen/backups/<str:name>", views.backup_download, name="backup_download"),
    path("einstellungen/info/", views.settings_about, name="about"),
]
