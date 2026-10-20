from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("kunden/", include("apps.customers.urls")),
    path("", include("apps.catalog.urls")),
    path("auftraege/", include("apps.orders.urls")),
    path("dokumente/", include("apps.documents.urls")),
    path("rechnungen/", include("apps.billing.urls")),
]

handler400 = "apps.core.errors.bad_request"
handler403 = "apps.core.errors.forbidden"
handler404 = "apps.core.errors.not_found"
handler500 = "apps.core.errors.server_error"
