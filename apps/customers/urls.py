from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="list"),
    path("neu/", views.customer_form, name="create"),
    path("<int:pk>/", views.customer_detail, name="detail"),
    path("<int:pk>/bearbeiten/", views.customer_form, name="edit"),
    path("<int:pk>/loeschen/", views.customer_delete, name="delete"),
    path("<int:pk>/datenauskunft/", views.customer_export, name="export"),
    path("<int:pk>/anonymisieren/", views.customer_anonymize, name="anonymize"),
]
