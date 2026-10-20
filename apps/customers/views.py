import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.numbering import next_number
from apps.core.permissions import admin_required

from . import services
from .forms import CustomerForm
from .models import Customer


def customer_list(request):
    qs = Customer.objects.annotate(order_count=Count("orders"), last_event=Max("orders__event_date")).order_by("last_name", "first_name", "pk")
    q = request.GET.get("q", "").strip()
    if q:
        for term in q.split():
            qs = qs.filter(
                Q(first_name__icontains=term) | Q(last_name__icontains=term) | Q(email__icontains=term)
                | Q(phone__icontains=term) | Q(number__icontains=term) | Q(city__icontains=term)
            )
    page = Paginator(qs, 30).get_page(request.GET.get("seite"))
    return render(request, "customers/list.html", {"page": page, "q": q, "total": Customer.objects.count()})


def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    orders = customer.orders.all().order_by("-event_date", "-created_at")
    return render(request, "customers/detail.html", {
        "customer": customer,
        "orders": orders,
        "retention_until": services.retention_until(customer),
        "can_delete": services.can_delete(customer),
    })


def customer_form(request, pk=None):
    customer = get_object_or_404(Customer, pk=pk) if pk else None
    if customer and customer.is_anonymized:
        messages.error(request, "Anonymisierte Kunden können nicht bearbeitet werden.")
        return redirect(customer)
    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        created = obj.pk is None
        if created:
            obj.number = next_number("customer")
        obj.save()
        audit.log(request.user, "customer", f"Kunde {'angelegt' if created else 'geändert'}: {obj.full_name}", obj=obj)
        messages.success(request, f"Kunde {obj.full_name} gespeichert.")
        return redirect(obj)
    return render(request, "customers/form.html", {"form": form, "customer": customer})


@require_POST
def customer_delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if not services.can_delete(customer):
        messages.error(request, "Kunden mit Aufträgen können nicht gelöscht werden. Nach Ablauf der Aufbewahrungsfristen ist eine Anonymisierung möglich.")
        return redirect(customer)
    name = customer.full_name
    audit.log(request.user, "customer", f"Kunde gelöscht: {name} ({customer.number})")
    customer.delete()
    messages.success(request, f"Kunde {name} gelöscht.")
    return redirect("customers:list")


def customer_export(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    data = services.export_data(customer)
    audit.log(request.user, "privacy", f"Datenauskunft exportiert: {customer.number}", obj=customer)
    response = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="Datenauskunft_{customer.number}.json"'
    return response


@admin_required
@require_POST
def customer_anonymize(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    try:
        services.anonymize(customer, request.user)
        messages.success(request, "Der Kunde wurde anonymisiert.")
    except services.PrivacyError as e:
        messages.error(request, str(e))
    return redirect(customer)
