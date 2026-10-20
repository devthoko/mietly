import base64
import os
import tempfile
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

os.environ.setdefault("MIETLY_TESTING", "1")
os.environ.setdefault("MIETLY_SECURE", "0")
os.environ.setdefault("MIETLY_DATA_DIR", tempfile.mkdtemp(prefix="mietly-test-"))
os.environ.setdefault("MIETLY_BACKUP_DIR", tempfile.mkdtemp(prefix="mietly-test-backup-"))

import pytest  # noqa: E402
from django.utils import timezone  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402


@pytest.fixture
def company(db):
    from apps.core.models import CompanySettings

    c = CompanySettings.get()
    c.name = "Blütenzauber Verleih"
    c.owner = "Maria Muster"
    c.street = "Lindenweg 3"
    c.zip_code = "12345"
    c.city = "Musterstadt"
    c.tax_number = "12/345/67890"
    c.iban = "DE89370400440532013000"
    c.bank_name = "Musterbank"
    c.deposit_required_before_handover = True
    c.save()
    return c


@pytest.fixture
def admin(db):
    from apps.core.models import User

    return User.objects.create_user("admin", password="Sicheres-Test-Passwort-1", role=User.Role.ADMIN, first_name="Ada")


@pytest.fixture
def staff(db):
    from apps.core.models import User

    return User.objects.create_user("mitarbeiter", password="Sicheres-Test-Passwort-2", role=User.Role.STAFF, first_name="Max")


@pytest.fixture
def customer(db):
    from apps.customers.models import Customer

    return Customer.objects.create(number="K-00001", first_name="Anna", last_name="Beispiel", email="anna@example.de",
                                   street="Musterweg 1", zip_code="12345", city="Musterstadt")


@pytest.fixture
def articles(db):
    from apps.catalog.models import Article, Category, StockMovement

    cat = Category.objects.create(name="Vasen")
    vase = Article.objects.create(number="A-00001", name="Glasvase hoch", category=cat, price=Decimal("4.50"),
                                  extra_day_price=Decimal("1.00"), replacement_value=Decimal("25.00"), deposit_per_unit=Decimal("5.00"),
                                  storage_location="Regal A1")
    arch = Article.objects.create(number="A-00002", name="Traubogen Holz", price=Decimal("89.00"),
                                  replacement_value=Decimal("450.00"), deposit_per_unit=Decimal("100.00"))
    StockMovement.objects.create(article=vase, quantity=20, reason="initial")
    StockMovement.objects.create(article=arch, quantity=1, reason="initial")
    return {"vase": vase, "arch": arch}


def make_order(user, customer, *, days_ahead=10, length=3):
    from apps.orders import services

    order = services.create_order(user, customer)
    start = timezone.now().replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    order.event_name = "Hochzeit Anna & Ben"
    order.event_date = timezone.localtime(start + timedelta(days=1)).date()
    order.event_location = "Gut Sonnenhof"
    order.handover_at = start
    order.return_at = start + timedelta(days=length)
    order.save()
    return order


@pytest.fixture
def order(admin, customer, company, articles):
    from apps.orders import services

    o = make_order(admin, customer)
    services.add_article(o, articles["vase"], 10, admin)
    services.add_article(o, articles["arch"], 1, admin)
    return o


def signature_data_url():
    img = Image.new("RGBA", (600, 200), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.line([(40, 150), (200, 60), (320, 140), (520, 50)], fill=(20, 30, 70, 255), width=5)
    buf = BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def sig():
    return signature_data_url()
