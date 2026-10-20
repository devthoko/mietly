from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.numbering import next_number

from .forms import ArticleFilterForm, ArticleForm, CategoryForm, PackageForm, PackageItemFormSet, StockMovementForm
from .models import Article, Category, Package, StockMovement


def article_list(request):
    form = ArticleFilterForm(request.GET or None)
    qs = Article.objects.select_related("category").annotate(_stock_sum=Coalesce(Sum("movements__quantity"), 0))
    show = request.GET.get("status", "aktiv")
    if show == "aktiv":
        qs = qs.filter(active=True)
    elif show == "inaktiv":
        qs = qs.filter(active=False)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(number__icontains=q) | Q(description__icontains=q) | Q(storage_location__icontains=q))
    cat = request.GET.get("kategorie")
    if cat:
        qs = qs.filter(category_id=cat)
    qs = qs.order_by("category__sort", "category__name", "name")
    page = Paginator(qs, 40).get_page(request.GET.get("seite"))
    for a in page:
        a._stock = a._stock_sum
    return render(request, "catalog/article_list.html", {
        "page": page, "form": form, "q": q, "show": show, "categories": Category.objects.all(), "cat": cat,
        "category_form": CategoryForm(),
    })


def article_detail(request, pk):
    from apps.orders.models import Order

    article = get_object_or_404(Article.objects.select_related("category"), pk=pk)
    today = timezone.localdate()
    upcoming = []
    orders = (
        Order.objects.exclude(status=Order.Status.CANCELLED)
        .filter(return_at__date__gte=today)
        .filter(Q(items__article=article) | Q(items__package__items__article=article))
        .distinct().select_related("customer").order_by("handover_at")
    )
    for o in orders:
        qty = o.article_quantities().get(article, 0)
        if qty:
            upcoming.append((o, qty))
    movement_form = StockMovementForm()
    return render(request, "catalog/article_detail.html", {
        "article": article,
        "movements": article.movements.select_related("created_by", "order")[:30],
        "upcoming": upcoming,
        "packages": Package.objects.filter(items__article=article).distinct(),
        "movement_form": movement_form,
    })


def article_form(request, pk=None):
    article = get_object_or_404(Article, pk=pk) if pk else None
    form = ArticleForm(request.POST or None, request.FILES or None, instance=article)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            created = obj.pk is None
            if created:
                obj.number = next_number("article")
            obj.save()
            if created and form.cleaned_data.get("initial_stock"):
                StockMovement.objects.create(
                    article=obj, quantity=form.cleaned_data["initial_stock"],
                    reason=StockMovement.Reason.INITIAL, created_by=request.user,
                )
        audit.log(request.user, "article", f"Artikel {'angelegt' if created else 'geändert'}: {obj.name}", obj=obj)
        messages.success(request, f"Artikel „{obj.name}“ gespeichert.")
        if created and "weiterer" in request.POST:
            return redirect("catalog:article_create")
        return redirect(obj)
    return render(request, "catalog/article_form.html", {"form": form, "article": article})


@require_POST
def article_stock(request, pk):
    article = get_object_or_404(Article, pk=pk)
    form = StockMovementForm(request.POST)
    if form.is_valid():
        qty = form.cleaned_data["amount"]
        if form.cleaned_data["direction"] == "out":
            if qty > article.stock:
                messages.error(request, f"Der Abgang ({qty}) ist größer als der aktuelle Bestand ({article.stock}).")
                return redirect(article)
            qty = -qty
        m = form.save(commit=False)
        m.article = article
        m.quantity = qty
        m.created_by = request.user
        m.save()
        audit.log(request.user, "stock", f"Bestand {article.name}: {qty:+d} ({m.get_reason_display()})", obj=article)
        messages.success(request, "Bestand aktualisiert.")
    else:
        messages.error(request, "Bitte Art, Grund und Menge prüfen. " + " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(article)


@require_POST
def article_delete(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if article.order_items.exists() or article.package_items.exists():
        article.active = False
        article.save(update_fields=["active"])
        messages.info(request, f"„{article.name}“ wird in Aufträgen oder Paketen verwendet und wurde daher deaktiviert statt gelöscht.")
        audit.log(request.user, "article", f"Artikel deaktiviert: {article.name}", obj=article)
        return redirect(article)
    try:
        with transaction.atomic():
            article.delete()
    except ProtectedError:
        # z. B. noch in Übergabe-/Rücknahmeprotokollen oder Schadensposten enthalten
        Article.objects.filter(pk=article.pk).update(active=False)
        messages.info(request, f"„{article.name}“ ist in Protokollen dokumentiert und wurde daher deaktiviert statt gelöscht.")
        audit.log(request.user, "article", f"Artikel deaktiviert: {article.name}", obj=article)
        return redirect(article)
    audit.log(request.user, "article", f"Artikel gelöscht: {article.name} ({article.number})")
    messages.success(request, "Artikel gelöscht.")
    return redirect("catalog:article_list")


@require_POST
def category_save(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None
    if "delete" in request.POST and category:
        if category.articles.exists():
            messages.error(request, "Kategorien mit Artikeln können nicht gelöscht werden.")
        else:
            category.delete()
            messages.success(request, "Kategorie gelöscht.")
        return redirect("catalog:article_list")
    form = CategoryForm(request.POST, instance=category)
    if form.is_valid():
        form.save()
        messages.success(request, "Kategorie gespeichert.")
    else:
        messages.error(request, "Die Kategorie konnte nicht gespeichert werden: " + " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("catalog:article_list")


# --------------------------------------------------------------------------
# Pakete
# --------------------------------------------------------------------------


def package_list(request):
    packages = Package.objects.prefetch_related("items__article").order_by("-active", "name")
    return render(request, "catalog/package_list.html", {"packages": packages})


def package_detail(request, pk):
    package = get_object_or_404(Package.objects.prefetch_related("items__article"), pk=pk)
    return render(request, "catalog/package_detail.html", {"package": package})


def package_form(request, pk=None):
    package = get_object_or_404(Package, pk=pk) if pk else Package()
    form = PackageForm(request.POST or None, instance=package)
    formset = PackageItemFormSet(request.POST or None, instance=package, prefix="items")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        articles = [f.cleaned_data["article"] for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if len(articles) != len(set(articles)):
            messages.error(request, "Jeder Artikel darf nur einmal im Paket vorkommen – bitte die Menge anpassen.")
        else:
            with transaction.atomic():
                created = package.pk is None
                form.save()
                formset.instance = package
                formset.save()
            audit.log(request.user, "package", f"Paket {'angelegt' if created else 'geändert'}: {package.name}", obj=package)
            messages.success(request, f"Paket „{package.name}“ gespeichert.")
            return redirect(package)
    return render(request, "catalog/package_form.html", {"form": form, "formset": formset, "package": package})


@require_POST
def package_delete(request, pk):
    package = get_object_or_404(Package, pk=pk)
    if package.order_items.exists():
        package.active = False
        package.save(update_fields=["active"])
        messages.info(request, "Das Paket wird in Aufträgen verwendet und wurde daher deaktiviert statt gelöscht.")
        return redirect(package)
    audit.log(request.user, "package", f"Paket gelöscht: {package.name}")
    package.delete()
    messages.success(request, "Paket gelöscht.")
    return redirect("catalog:package_list")
