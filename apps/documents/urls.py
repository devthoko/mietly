from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.document_list, name="list"),
    path("<int:pk>/", views.download, name="download"),
    path("<int:pk>/unterschreiben/", views.sign, name="sign"),
    path("<int:pk>/hochladen/", views.upload_signed, name="upload_signed"),
    path("<int:pk>/email/", views.email, name="email"),
    path("<int:pk>/drucken/", views.print_document, name="print"),
    path("email/<int:log_pk>/erneut/", views.email_retry, name="email_retry"),
]
