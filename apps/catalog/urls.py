from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("artikel/", views.article_list, name="article_list"),
    path("artikel/neu/", views.article_form, name="article_create"),
    path("artikel/<int:pk>/", views.article_detail, name="article_detail"),
    path("artikel/<int:pk>/bearbeiten/", views.article_form, name="article_edit"),
    path("artikel/<int:pk>/bestand/", views.article_stock, name="article_stock"),
    path("artikel/<int:pk>/loeschen/", views.article_delete, name="article_delete"),
    path("artikel/kategorien/", views.category_save, name="category_create"),
    path("artikel/kategorien/<int:pk>/", views.category_save, name="category_edit"),
    path("pakete/", views.package_list, name="package_list"),
    path("pakete/neu/", views.package_form, name="package_create"),
    path("pakete/<int:pk>/", views.package_detail, name="package_detail"),
    path("pakete/<int:pk>/bearbeiten/", views.package_form, name="package_edit"),
    path("pakete/<int:pk>/loeschen/", views.package_delete, name="package_delete"),
]
