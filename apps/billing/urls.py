from django.urls import path

from . import views

app_name = "billing"

urlpatterns = [
    path("", views.invoice_list, name="list"),
    path("zahlungen/", views.payment_list, name="payments"),
    path("monatsexport/", views.month_export, name="month_export"),
]
