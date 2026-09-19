from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.orders.models import OrderStatus
from apps.orders.selectors import order_for_buyer_or_404
from apps.orders.services import expire_order_reservation

from .forms import RegistrationParticipantFormSet
from .models import Registration
from .services import (
    ensure_registration_slots,
    update_registration_participants,
)


def _service_error_messages(error):
    if hasattr(error, "message_dict"):
        return [
            message
            for messages_list in error.message_dict.values()
            for message in messages_list
        ]

    return list(error.messages)


def _participant_payload(formset):
    """
    Transforma somente os dados validados do formulário em uma
    estrutura aceita pelo serviço.
    """
    return [
        {
            "registration_id": form.cleaned_data["id"].id,
            "full_name": form.cleaned_data["full_name"],
            "document_type": (
                form.cleaned_data["document_type"]
            ),
            "document_number": (
                form.cleaned_data["document_number"]
            ),
            "birth_date": form.cleaned_data["birth_date"],
            "email": form.cleaned_data["email"],
            "phone": form.cleaned_data["phone"],
            "emergency_contact_name": (
                form.cleaned_data[
                    "emergency_contact_name"
                ]
            ),
            "emergency_contact_phone": (
                form.cleaned_data[
                    "emergency_contact_phone"
                ]
            ),
        }
        for form in formset.forms
    ]


@login_required
@require_http_methods(["GET", "POST"])
def participant_details(request, public_code):
    order = order_for_buyer_or_404(
        buyer=request.user,
        public_code=public_code,
    )

    if order.is_expirable:
        expiration_result = expire_order_reservation(
            order_id=order.id,
        )

        messages.error(
            request,
            (
                "O prazo da reserva terminou e as vagas "
                "foram liberadas."
            ),
        )

        return redirect(
            "orders:checkout-detail",
            public_code=expiration_result.order.public_code,
        )

    if order.status != OrderStatus.AWAITING_PAYMENT:
        messages.error(
            request,
            (
                "Este pedido não aceita alterações nos "
                "participantes."
            ),
        )

        return redirect(
            "orders:checkout-detail",
            public_code=order.public_code,
        )

    try:
        ensure_registration_slots(
            order_id=order.id,
            buyer=request.user,
        )
    except ValidationError as error:
        for error_message in _service_error_messages(error):
            messages.error(
                request,
                error_message,
            )

        return redirect(
            "orders:checkout-detail",
            public_code=order.public_code,
        )

    registrations = (
        Registration.objects
        .filter(
            order_item__order=order,
        )
        .select_related(
            "order_item",
            "order_item__ticket_type",
            "order_item__ticket_lot",
        )
        .order_by(
            "order_item__created_at",
            "position",
        )
    )

    service_errors = []

    if request.method == "POST":
        formset = RegistrationParticipantFormSet(
            request.POST,
            queryset=registrations,
            prefix="participants",
        )

        if formset.is_valid():
            try:
                update_registration_participants(
                    order_id=order.id,
                    buyer=request.user,
                    participants_data=(
                        _participant_payload(formset)
                    ),
                )
            except ValidationError as error:
                service_errors = (
                    _service_error_messages(error)
                )
            else:
                messages.success(
                    request,
                    (
                        "Dados dos participantes salvos "
                        "com sucesso."
                    ),
                )

                return redirect(
                    "registrations:participants",
                    public_code=order.public_code,
                )
    else:
        formset = RegistrationParticipantFormSet(
            queryset=registrations,
            prefix="participants",
        )

    all_completed = (
        registrations.exists()
        and not registrations.filter(
            completed_at__isnull=True,
        ).exists()
    )

    context = {
        "order": order,
        "formset": formset,
        "service_errors": service_errors,
        "all_completed": all_completed,
    }

    return render(
        request,
        "registrations/participant_form.html",
        context,
    )