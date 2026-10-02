from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from apps.events.selectors import (
    editable_event_for_organization_or_404,
)
from apps.organizations.decorators import organizer_required

from .forms import EventKitForm, KitOptionForm
from .selectors import (
    kit_for_event_or_404,
    kit_management_event_or_404,
    kits_for_event,
    option_availabilities_for_kit,
    option_for_kit_or_404,
)
from .services import (
    create_event_kit,
    create_kit_option,
    update_event_kit,
    update_kit_option,
)


def _add_validation_errors_to_form(form, error):
    """
    Transfere erros da camada de serviços para o formulário.
    """

    if hasattr(error, "message_dict"):
        for field_name, error_messages in (
            error.message_dict.items()
        ):
            target_field = (
                field_name
                if field_name in form.fields
                else None
            )

            for error_message in error_messages:
                form.add_error(
                    target_field,
                    error_message,
                )
    else:
        for error_message in error.messages:
            form.add_error(None, error_message)


@organizer_required
def organizer_kit_configuration(request, event_id):
    event = kit_management_event_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    kits = list(kits_for_event(event=event))
    kit_rows = []

    total_stock = 0
    total_reserved = 0
    total_available = 0

    for kit in kits:
        option_rows = option_availabilities_for_kit(
            kit=kit,
        )

        kit_stock = sum(
            row.option.stock_quantity
            for row in option_rows
        )
        kit_reserved = sum(
            row.reserved_quantity
            for row in option_rows
        )
        kit_available = sum(
            row.available_quantity
            for row in option_rows
        )

        total_stock += kit_stock
        total_reserved += kit_reserved
        total_available += kit_available

        kit_rows.append(
            {
                "kit": kit,
                "option_rows": option_rows,
                "total_stock": kit_stock,
                "total_reserved": kit_reserved,
                "total_available": kit_available,
            }
        )

    context = {
        "organization": request.active_organization,
        "event": event,
        "kit_rows": kit_rows,
        "has_ticket_types": event.ticket_types.exists(),
        "total_stock": total_stock,
        "total_reserved": total_reserved,
        "total_available": total_available,
    }

    return render(
        request,
        "kits/organizer/kit_configuration.html",
        context,
    )


@organizer_required
def organizer_kit_create(request, event_id):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    if not event.ticket_types.exists():
        messages.warning(
            request,
            (
                "Cadastre pelo menos um tipo de ingresso "
                "antes de criar um kit."
            ),
        )

        return redirect(
            "events:ticket-configuration",
            event_id=event.id,
        )

    if request.method == "POST":
        form = EventKitForm(
            request.POST,
            event=event,
        )

        if form.is_valid():
            try:
                create_event_kit(
                    organization=request.active_organization,
                    event_id=event.id,
                    cleaned_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_validation_errors_to_form(
                    form,
                    error,
                )
            else:
                messages.success(
                    request,
                    "Kit cadastrado com sucesso.",
                )

                return redirect(
                    "kits:configuration",
                    event_id=event.id,
                )
    else:
        form = EventKitForm(event=event)

    context = {
        "organization": request.active_organization,
        "event": event,
        "form": form,
        "page_title": "Cadastrar kit",
        "submit_label": "Salvar kit",
    }

    return render(
        request,
        "kits/organizer/kit_form.html",
        context,
    )


@organizer_required
def organizer_kit_update(
    request,
    event_id,
    kit_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    kit = kit_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        kit_id=kit_id,
    )

    if request.method == "POST":
        form = EventKitForm(
            request.POST,
            event=event,
            instance=kit,
        )

        if form.is_valid():
            try:
                update_event_kit(
                    organization=request.active_organization,
                    event_id=event.id,
                    kit_id=kit.id,
                    cleaned_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_validation_errors_to_form(
                    form,
                    error,
                )
            else:
                messages.success(
                    request,
                    "Kit atualizado com sucesso.",
                )

                return redirect(
                    "kits:configuration",
                    event_id=event.id,
                )
    else:
        form = EventKitForm(
            event=event,
            instance=kit,
        )

    context = {
        "organization": request.active_organization,
        "event": event,
        "kit": kit,
        "form": form,
        "page_title": "Editar kit",
        "submit_label": "Salvar alterações",
    }

    return render(
        request,
        "kits/organizer/kit_form.html",
        context,
    )


@organizer_required
def organizer_kit_option_create(
    request,
    event_id,
    kit_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    kit = kit_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        kit_id=kit_id,
    )

    if request.method == "POST":
        form = KitOptionForm(request.POST)

        if form.is_valid():
            try:
                create_kit_option(
                    organization=request.active_organization,
                    event_id=event.id,
                    kit_id=kit.id,
                    cleaned_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_validation_errors_to_form(
                    form,
                    error,
                )
            else:
                messages.success(
                    request,
                    "Opção de kit cadastrada com sucesso.",
                )

                return redirect(
                    "kits:configuration",
                    event_id=event.id,
                )
    else:
        form = KitOptionForm()

    context = {
        "organization": request.active_organization,
        "event": event,
        "kit": kit,
        "form": form,
        "page_title": "Adicionar opção",
        "submit_label": "Salvar opção",
    }

    return render(
        request,
        "kits/organizer/kit_option_form.html",
        context,
    )


@organizer_required
def organizer_kit_option_update(
    request,
    event_id,
    kit_id,
    option_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    kit = kit_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        kit_id=kit_id,
    )

    option = option_for_kit_or_404(
        organization=request.active_organization,
        event_id=event.id,
        kit_id=kit.id,
        option_id=option_id,
    )

    if request.method == "POST":
        form = KitOptionForm(
            request.POST,
            instance=option,
        )

        if form.is_valid():
            try:
                update_kit_option(
                    organization=request.active_organization,
                    event_id=event.id,
                    kit_id=kit.id,
                    option_id=option.id,
                    cleaned_data=form.cleaned_data,
                )
            except ValidationError as error:
                _add_validation_errors_to_form(
                    form,
                    error,
                )
            else:
                messages.success(
                    request,
                    "Opção de kit atualizada.",
                )

                return redirect(
                    "kits:configuration",
                    event_id=event.id,
                )
    else:
        form = KitOptionForm(instance=option)

    context = {
        "organization": request.active_organization,
        "event": event,
        "kit": kit,
        "option": option,
        "form": form,
        "page_title": "Editar opção",
        "submit_label": "Salvar alterações",
    }

    return render(
        request,
        "kits/organizer/kit_option_form.html",
        context,
    )