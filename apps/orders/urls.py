from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("neu/", views.order_create, name="create"),
    path("<int:pk>/", views.order_detail, name="detail"),
    path("<int:pk>/kopieren/", views.duplicate, name="duplicate"),
    path("<int:pk>/loeschen/", views.delete_draft, name="delete_draft"),
    # 1 & 2
    path("<int:pk>/kunde/", views.set_customer, name="set_customer"),
    path("<int:pk>/kunde/suche/", views.customer_picker, name="customer_picker"),
    path("<int:pk>/event/", views.save_event, name="save_event"),
    # 3
    path("<int:pk>/positionen/suche/", views.item_search, name="item_search"),
    path("<int:pk>/positionen/neu/", views.item_add, name="item_add"),
    path("<int:pk>/positionen/individuell/", views.item_custom, name="item_custom"),
    path("<int:pk>/positionen/<int:item_pk>/", views.item_update, name="item_update"),
    path("<int:pk>/positionen/<int:item_pk>/entfernen/", views.item_remove, name="item_remove"),
    path("<int:pk>/positionen/preise/", views.reprice, name="reprice"),
    path("<int:pk>/kaution/betrag/", views.deposit_amount, name="deposit_amount"),
    path("<int:pk>/angebot/", views.create_offer, name="create_offer"),
    # 4 & 5
    path("<int:pk>/vertrag/", views.create_contract, name="create_contract"),
    path("<int:pk>/rechnung/", views.issue_invoice, name="issue_invoice"),
    path("<int:pk>/rechnung/<int:invoice_pk>/storno/", views.cancel_invoice, name="cancel_invoice"),
    path("<int:pk>/zahlungen/", views.add_payment, name="add_payment"),
    path("<int:pk>/zahlungen/erstattung/", views.add_refund, name="add_refund"),
    path("<int:pk>/zahlungen/<int:payment_pk>/loeschen/", views.delete_payment, name="delete_payment"),
    path("<int:pk>/kaution/", views.add_deposit, name="add_deposit"),
    # 6 & 7
    path("<int:pk>/packliste/", views.create_packing_list, name="create_packing_list"),
    path("<int:pk>/uebergabe/start/", views.start_handover, name="start_handover"),
    path("<int:pk>/uebergabe/", views.save_handover, name="save_handover"),
    path("<int:pk>/uebergabe/abschliessen/", views.complete_handover, name="complete_handover"),
    path("<int:pk>/fotos/<str:stage>/", views.upload_photos, name="upload_photos"),
    path("<int:pk>/fotos/<int:photo_pk>/loeschen/", views.delete_photo, name="delete_photo"),
    # 8 & 9
    path("<int:pk>/ruecknahme/start/", views.start_return, name="start_return"),
    path("<int:pk>/ruecknahme/", views.save_return, name="save_return"),
    path("<int:pk>/schaeden/", views.add_damage, name="add_damage"),
    path("<int:pk>/schaeden/<int:damage_pk>/", views.update_damage, name="update_damage"),
    path("<int:pk>/schaeden/<int:damage_pk>/loeschen/", views.delete_damage, name="delete_damage"),
    path("<int:pk>/abrechnung/", views.settle, name="settle"),
    path("<int:pk>/abschliessen/", views.close_order, name="close"),
    path("<int:pk>/stornieren/", views.cancel_order, name="cancel"),
    path("<int:pk>/kaution/rueckzahlung/", views.refund_deposit_cancelled, name="refund_deposit_cancelled"),
]
