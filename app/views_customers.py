"""Kundenverwaltung (international). Ein Kunde hat mehrere Projekte (Mandanten)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from app.forms import CustomerForm
from app.models import Customer
from app.permissions import pm_or_admin_required


@login_required
@pm_or_admin_required
def customer_list(request):
    customers = (
        Customer.objects.filter(archived=False)
        .annotate(n_projects=Count("projects", distinct=True))
    )
    return render(request, "customers.html", {
        "active_tab": "customers",
        "customers": customers,
    })


@login_required
@pm_or_admin_required
def customer_form(request, pk=None):
    """Anlegen oder Bearbeiten eines Kunden mit allen Attributen."""
    customer = get_object_or_404(Customer, pk=pk) if pk else None
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            obj = form.save(commit=False)
            if not obj.number:
                # Kundennummer aus Name generieren, eindeutig.
                base = (slugify(obj.name) or "kunde")[:32]
                num, i = base, 1
                while Customer.objects.filter(number=num).exclude(pk=obj.pk).exists():
                    i += 1
                    num = f"{base}-{i}"[:32]
                obj.number = num
            obj.save()
            messages.success(request, f"Kunde „{obj.name}“ gespeichert.")
            return redirect("customers")
    else:
        form = CustomerForm(instance=customer)
    return render(request, "customer_form.html", {
        "active_tab": "customers",
        "form": form,
        "customer": customer,
    })


@login_required
@pm_or_admin_required
def customer_archive(request, pk):
    if request.method != "POST":
        return redirect("customers")
    customer = get_object_or_404(Customer, pk=pk)
    customer.archived = True
    customer.save(update_fields=["archived"])
    messages.info(request, f"Kunde „{customer.name}“ archiviert.")
    return redirect("customers")


@login_required
@pm_or_admin_required
def customer_delete(request, pk):
    """CRUD: endgültiges Löschen. Projekte des Kunden bleiben (customer=NULL)."""
    if request.method != "POST":
        return redirect("customers")
    customer = get_object_or_404(Customer, pk=pk)
    name = customer.name
    customer.delete()
    messages.warning(request, f"Kunde „{name}“ endgültig gelöscht.")
    return redirect("customers")
