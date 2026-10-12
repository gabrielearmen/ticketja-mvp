from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.kits.selectors import (
    participant_kit_catalog_for_ticket_types,
)
from apps.orders.models import OrderStatus
from apps.orders.selectors import order_for_buyer_or_404
from apps.orders.services import expire_order_reservation
from apps.payments.gateways.base import PaymentGatewayError
from apps.payments.services import initiate_order_payment

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

    if hasattr(error, "messages"):
        return list(error.messages)

    return [str(error)]


def _participant_payload(formset):
    """
    Transforma somente dados validados na estrutura aceita pelo
    serviço transacional.
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
            "kit_selections": (
                form.kit_selection_payload()
            ),
        }
        for form in formset.forms
    ]


def _required_kit_choices_are_complete(
    *,
    registrations,
    kit_catalog,
):
    for registration in registrations:
        applicable_kits = kit_catalog.get(
            registration.order_item.ticket_type_id,
            (),
        )

        required_kit_ids = {
            kit_entry.kit.id
            for kit_entry in applicable_kits
            if kit_entry.kit.is_required
        }

        selected_kit_ids = {
            selection.kit_id
            for selection
            in registration.kit_selections.all()
        }

        if not required_kit_ids.issubset(
            selected_kit_ids
        ):
            return False

    return True


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
            public_code=(
                expiration_result.order.public_code
            ),
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
        .prefetch_related(
            "kit_selections",
            "kit_selections__kit",
            "kit_selections__option",
        )
        .order_by(
            "order_item__created_at",
            "position",
        )
    )

    ticket_type_ids = set(
        registrations.values_list(
            "order_item__ticket_type_id",
            flat=True,
        )
    )

    kit_catalog = (
        participant_kit_catalog_for_ticket_types(
            ticket_type_ids=ticket_type_ids,
        )
    )

    form_kwargs = {
        "kit_catalog_by_ticket_type": kit_catalog,
    }

    service_errors = []

    if request.method == "POST":
        formset = RegistrationParticipantFormSet(
            request.POST,
            queryset=registrations,
            prefix="participants",
            form_kwargs=form_kwargs,
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
                submit_action = request.POST.get(
                    "submit_action",
                    "save",
                )

                if submit_action == "continue":
                    if (
                        order.total > 0
                        and settings.MARKETPLACE_PAYMENTS_ENABLED
                    ):
                        return redirect(
                            "payments:payer-details",
                            public_code=order.public_code,
                        )

                    try:
                        payment_result = (
                            initiate_order_payment(
                                order_id=order.id,
                                buyer=request.user,
                            )
                        )
                    except (
                        ValidationError,
                        PaymentGatewayError,
                    ) as error:
                        for error_message in (
                            _service_error_messages(error)
                        ):
                            messages.error(
                                request,
                                error_message,
                            )

                        return redirect(
                            "registrations:participants",
                            public_code=(
                                order.public_code
                            ),
                        )

                    if payment_result.is_free:
                        messages.success(
                            request,
                            (
                                "Inscrição gratuita "
                                "confirmada com sucesso."
                            ),
                        )
                    else:
                        messages.success(
                            request,
                            (
                                "Participantes salvos e "
                                "cobrança PIX preparada."
                            ),
                        )

                    return redirect(
                        "payments:detail",
                        public_code=order.public_code,
                    )

                messages.success(
                    request,
                    (
                        "Participantes e kits salvos "
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
            form_kwargs=form_kwargs,
        )

    registration_list = list(registrations)

    personal_data_completed = (
        bool(registration_list)
        and all(
            registration.completed_at is not None
            for registration in registration_list
        )
    )

    required_kits_completed = (
        _required_kit_choices_are_complete(
            registrations=registration_list,
            kit_catalog=kit_catalog,
        )
    )

    all_completed = (
        personal_data_completed
        and required_kits_completed
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
