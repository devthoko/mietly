"""Beispieldaten zum Ausprobieren (nur für Test- und Vorführsysteme)."""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.models import Article, Category, Package, PackageItem, StockMovement
from apps.core.models import CompanySettings
from apps.core.numbering import next_number
from apps.customers.models import Customer

ARTICLES = [
    ("Vasen", "Glasvase hoch, 40 cm", "4.50", "1.00", "25.00", "5.00", 60, "Regal A1"),
    ("Vasen", "Bauchige Vase Klarglas", "3.50", "0.50", "18.00", "3.00", 40, "Regal A2"),
    ("Vasen", "Flaschenvase Vintage (Set à 3)", "6.00", "1.00", "21.00", "5.00", 25, "Regal A3"),
    ("Kerzen & Licht", "Kerzenständer Messing, 3-armig", "7.50", "1.50", "45.00", "10.00", 30, "Regal B1"),
    ("Kerzen & Licht", "Windlicht Glas mit Holzsockel", "3.00", "0.50", "15.00", "3.00", 80, "Regal B2"),
    ("Kerzen & Licht", "Lichterkette warmweiß, 10 m", "8.00", "2.00", "35.00", "10.00", 20, "Kiste B5"),
    ("Traubögen & Deko", "Traubogen Holz, sechseckig", "89.00", "15.00", "450.00", "100.00", 2, "Lager hinten"),
    ("Traubögen & Deko", "Traubogen Metall, rund", "79.00", "15.00", "380.00", "100.00", 1, "Lager hinten"),
    ("Traubögen & Deko", "Willkommensschild Spiegel", "29.00", "5.00", "120.00", "30.00", 3, "Regal C1"),
    ("Tischdeko", "Tischläufer Leinen, natur", "4.00", "0.50", "19.00", "3.00", 50, "Schrank D1"),
    ("Tischdeko", "Platzteller Gold", "1.20", "0.20", "6.00", "1.00", 200, "Schrank D2"),
]

CUSTOMERS = [
    ("Frau", "Lena", "Hoffmann", "lena.hoffmann@example.de", "0151 23456789", "Rosenweg 12", "80331", "München"),
    ("Herr", "Jonas", "Becker", "jonas.becker@example.de", "0170 9876543", "Am Markt 5", "80539", "München"),
    ("Frau", "Sophie", "Wagner", "sophie.wagner@example.de", "0176 1122334", "Lindenallee 8", "85354", "Freising"),
]


class Command(BaseCommand):
    help = "Legt Beispieldaten an (Kategorien, Artikel, Pakete, Kunden). Nicht auf Produktivsystemen verwenden."

    def add_arguments(self, parser):
        parser.add_argument("--ja", action="store_true", help="Bestätigt, dass Beispieldaten angelegt werden sollen")

    @transaction.atomic
    def handle(self, *args, ja=False, **opts):
        if not ja:
            raise CommandError("Bitte mit --ja bestätigen. Beispieldaten gehören nicht in ein Produktivsystem.")
        if Article.objects.exists():
            raise CommandError("Es sind bereits Artikel vorhanden – Beispieldaten werden nicht angelegt.")
        c = CompanySettings.get()
        c.name = c.name if c.name != "Mein Verleih" else "Blütenzauber Eventverleih"
        c.owner = c.owner or "Maria Muster"
        c.street = c.street or "Lindenweg 3"
        c.zip_code = c.zip_code or "80331"
        c.city = c.city or "München"
        c.phone = c.phone or "089 1234567"
        c.email = c.email or "hallo@bluetenzauber.example"
        c.tax_number = c.tax_number or "143/123/45678"
        c.iban = c.iban or "DE89370400440532013000"
        c.bank_name = c.bank_name or "Musterbank München"
        c.save()

        cats = {}
        articles = {}
        for i, (cat, name, price, extra, repl, dep, stock, loc) in enumerate(ARTICLES):
            cats.setdefault(cat, Category.objects.get_or_create(name=cat, defaults={"sort": len(cats)})[0])
            a = Article.objects.create(
                number=next_number("article"), name=name, category=cats[cat], price=Decimal(price), extra_day_price=Decimal(extra),
                replacement_value=Decimal(repl), deposit_per_unit=Decimal(dep), storage_location=loc,
            )
            StockMovement.objects.create(article=a, quantity=stock, reason="initial")
            articles[name] = a

        p = Package.objects.create(name="Tischdeko Hochzeit – 10 Tische", price=Decimal("149.00"),
                                   description="Pro Tisch: Läufer, zwei Vasen, drei Windlichter.")
        for name, qty in [("Tischläufer Leinen, natur", 10), ("Glasvase hoch, 40 cm", 20), ("Windlicht Glas mit Holzsockel", 30)]:
            PackageItem.objects.create(package=p, article=articles[name], quantity=qty)
        p2 = Package.objects.create(name="Trauung im Freien", description="Traubogen, Willkommensschild und Lichterkette.")
        for name, qty in [("Traubogen Holz, sechseckig", 1), ("Willkommensschild Spiegel", 1), ("Lichterkette warmweiß, 10 m", 2)]:
            PackageItem.objects.create(package=p2, article=articles[name], quantity=qty)

        for sal, fn, ln, email, phone, street, zipc, city in CUSTOMERS:
            Customer.objects.create(number=next_number("customer"), salutation=sal, first_name=fn, last_name=ln, email=email,
                                    phone=phone, street=street, zip_code=zipc, city=city)
        self.stdout.write(self.style.SUCCESS(f"{len(ARTICLES)} Artikel, 2 Pakete und {len(CUSTOMERS)} Kunden angelegt."))
