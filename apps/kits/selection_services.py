import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q

from apps.orders.models import OrderStatus

from .models import (
    EventKit,
    KitOption,
    RegistrationKitSelection,
    TicketTypeKit,
)


@dataclass(frozen=True, slots=True)
class KitSelectionUpdateResult:
    selections: tuple[RegistrationKitSelection, ...]
    created_count: int
    updated_count: int
    deleted_count: int


def _normalize_uuid(*, value, field_name):
    if isinstance(value, uuid.UUID):
        return value

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValidationError(
            {
                field_name: (
                    "O identificador da escolha de kit "
                    "é inválido."
                )
            }
        ) from error


def _submitted_selections_by_kit(
    *,
    participant_data,
):
    raw_selections = participant_data.get(
        "kit_selections",
        [],
    )

    if not isinstance(raw_selections, (list, tuple)):
        raise ValidationError(
            {
                "participants": (
                    "As escolhas de kit são inválidas."
                )
            }
        )

    selections_by_kit = {}

    for raw_selection in raw_selections:
        if not isinstance(raw_selection, dict):
            raise ValidationError(
                {
                    "participants": (
                        "As escolhas de kit são inválidas."
                    )
                }
            )

        kit_id = _normalize_uuid(
            value=raw_selection.get("kit_id"),
            field_name="participants",
        )

        if kit_id in selections_by_kit:
            raise ValidationError(
                {
                    "participants": (
                        "O mesmo kit foi enviado mais de "
                        "uma vez para um participante."
                    )
                }
            )

        raw_option_id = raw_selection.get("option_id")

        option_id = None

        if raw_option_id not in (None, ""):
            option_id = _normalize_uuid(
                value=raw_option_id,
                field_name="participants",
            )

        selections_by_kit[kit_id] = option_id

    return selections_by_kit


@transaction.atomic
def synchronize_registration_kit_selections(
    *,
    registrations,
    submitted_by_registration,
    at,
):
    """
    Sincroniza escolhas individuais de kits.

    Esta função é chamada dentro da mesma transação que salva os
    participantes. Ela:

    - valida os kits aplicáveis a cada ingresso;
    - exige escolhas dos kits obrigatórios;
    - bloqueia as opções no PostgreSQL;
    - recalcula o estoque reservado;
    - impede estoque negativo;
    - cria, altera ou remove escolhas opcionais;
    - preserva a idempotência.
    """

    registration_list = list(registrations)

    if not registration_list:
        raise ValidationError(
            {
                "participants": (
                    "O pedido não possui inscrições para "
                    "receber escolhas de kit."
                )
            }
        )

    registration_ids = {
        registration.id
        for registration in registration_list
    }

    if set(submitted_by_registration) != registration_ids:
        raise ValidationError(
            {
                "participants": (
                    "As escolhas de kit não correspondem "
                    "às inscrições deste pedido."
                )
            }
        )

    ticket_type_ids = {
        registration.order_item.ticket_type_id
        for registration in registration_list
    }

    assignments = list(
        TicketTypeKit.objects
        .select_for_update()
        .select_related("kit")
        .filter(
            ticket_type_id__in=ticket_type_ids,
            kit__is_active=True,
        )
        .order_by(
            "ticket_type_id",
            "kit_id",
        )
    )

    kits_by_ticket_type = defaultdict(dict)

    for assignment in assignments:
        kits_by_ticket_type[
            assignment.ticket_type_id
        ][assignment.kit_id] = assignment.kit

    desired_options = {}
    selected_option_ids = set()

    for registration in registration_list:
        participant_data = submitted_by_registration[
            registration.id
        ]

        submitted_selections = (
            _submitted_selections_by_kit(
                participant_data=participant_data,
            )
        )

        expected_kits = kits_by_ticket_type.get(
            registration.order_item.ticket_type_id,
            {},
        )

        if set(submitted_selections) != set(expected_kits):
            raise ValidationError(
                {
                    "participants": (
                        "As escolhas de kit não correspondem "
                        "ao tipo de ingresso do participante."
                    )
                }
            )

        for kit_id, kit in expected_kits.items():
            option_id = submitted_selections[kit_id]

            if kit.is_required and option_id is None:
                raise ValidationError(
                    {
                        "participants": (
                            f"Selecione uma opção de "
                            f"“{kit.name}” para todos os "
                            f"participantes."
                        )
                    }
                )

            selection_key = (
                registration.id,
                kit_id,
            )

            desired_options[selection_key] = option_id

            if option_id is not None:
                selected_option_ids.add(option_id)

    locked_options = list(
        KitOption.objects
        .select_for_update()
        .select_related("kit")
        .filter(id__in=selected_option_ids)
        .order_by("id")
    )

    options_by_id = {
        option.id: option
        for option in locked_options
    }

    if len(options_by_id) != len(selected_option_ids):
        raise ValidationError(
            {
                "participants": (
                    "Uma das opções de kit não existe "
                    "ou não está mais disponível."
                )
            }
        )

    for (
        registration_id,
        kit_id,
    ), option_id in desired_options.items():
        if option_id is None:
            continue

        option = options_by_id[option_id]

        if option.kit_id != kit_id:
            raise ValidationError(
                {
                    "participants": (
                        "Uma opção foi enviada para um kit "
                        "ao qual ela não pertence."
                    )
                }
            )

        if not option.is_active:
            raise ValidationError(
                {
                    "participants": (
                        f"A opção “{option.name}” não está "
                        "mais disponível."
                    )
                }
            )

    existing_selections = list(
        RegistrationKitSelection.objects
        .select_for_update()
        .select_related(
            "registration",
            "registration__order_item",
            "registration__order_item__order",
            "registration__order_item__ticket_type",
            "kit",
            "option",
        )
        .filter(
            registration_id__in=registration_ids,
        )
        .order_by(
            "registration_id",
            "kit_id",
        )
    )

    existing_by_key = {
        (
            selection.registration_id,
            selection.kit_id,
        ): selection
        for selection in existing_selections
    }

    unexpected_existing_keys = (
        set(existing_by_key)
        - set(desired_options)
    )

    if unexpected_existing_keys:
        raise ValidationError(
            {
                "participants": (
                    "As escolhas de kit existentes estão "
                    "inconsistentes com os ingressos."
                )
            }
        )

    holding_inventory_filter = (
        Q(
            registration__order_item__order__status=(
                OrderStatus.PAID
            )
        )
        | Q(
            registration__order_item__order__status=(
                OrderStatus.AWAITING_PAYMENT
            ),
            registration__order_item__order__reservation_expires_at__gt=at,
        )
    )

    committed_rows = (
        RegistrationKitSelection.objects
        .filter(
            option_id__in=selected_option_ids,
        )
        .exclude(
            registration_id__in=registration_ids,
        )
        .filter(holding_inventory_filter)
        .values("option_id")
        .annotate(total=Count("id"))
    )

    committed_by_option = {
        row["option_id"]: row["total"]
        for row in committed_rows
    }

    requested_by_option = Counter(
        option_id
        for option_id in desired_options.values()
        if option_id is not None
    )

    for option_id, requested_quantity in (
        requested_by_option.items()
    ):
        option = options_by_id[option_id]

        committed_quantity = committed_by_option.get(
            option_id,
            0,
        )

        available_quantity = max(
            option.stock_quantity - committed_quantity,
            0,
        )

        if requested_quantity > available_quantity:
            raise ValidationError(
                {
                    "participants": (
                        f"A opção “{option.kit.name} — "
                        f"{option.name}” não possui estoque "
                        "suficiente. Restam "
                        f"{available_quantity} unidade(s)."
                    )
                }
            )

    created_count = 0
    updated_count = 0
    deleted_count = 0

    registrations_by_id = {
        registration.id: registration
        for registration in registration_list
    }

    kits_by_id = {
        kit_id: kit
        for ticket_kits in kits_by_ticket_type.values()
        for kit_id, kit in ticket_kits.items()
    }

    for selection_key, option_id in desired_options.items():
        registration_id, kit_id = selection_key
        existing_selection = existing_by_key.get(
            selection_key
        )

        if option_id is None:
            if existing_selection is not None:
                existing_selection.delete()
                deleted_count += 1

            continue

        option = options_by_id[option_id]

        if existing_selection is None:
            selection = RegistrationKitSelection(
                registration=registrations_by_id[
                    registration_id
                ],
                kit=kits_by_id[kit_id],
                option=option,
            )

            selection.full_clean()
            selection.save(force_insert=True)
            created_count += 1
        elif existing_selection.option_id != option_id:
            existing_selection.option = option
            existing_selection.full_clean()
            existing_selection.save(
                update_fields=(
                    "option",
                    "updated_at",
                )
            )
            updated_count += 1

    saved_selections = tuple(
        RegistrationKitSelection.objects
        .filter(
            registration_id__in=registration_ids,
        )
        .select_related(
            "registration",
            "kit",
            "option",
        )
        .order_by(
            "registration_id",
            "kit_id",
        )
    )

    return KitSelectionUpdateResult(
        selections=saved_selections,
        created_count=created_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
    )