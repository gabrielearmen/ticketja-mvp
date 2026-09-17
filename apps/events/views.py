from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .rules import commercial_configuration_errors

from apps.organizations.decorators import organizer_required

from .forms import (
    EventForm,
    TicketLotForm,
    TicketTypeForm,
)

from .selectors import (
    editable_event_for_organization_or_404,
    event_for_organization_or_404,
    events_for_organization,
    ticket_type_for_event_or_404,
    ticket_types_for_event,
    ticket_lot_for_type_or_404,
)

from .services import (
    cancel_event,
    create_draft_event,
    create_ticket_type,
    publish_event,
    update_draft_event,
    update_ticket_type,
    create_ticket_lot,
    update_ticket_lot,
)

@organizer_required
def organizer_event_list(request):
    events = events_for_organization(
        request.active_organization
    )

    context = {
        "organization": request.active_organization,
        "events": events,
    }

    return render(
        request,
        "events/organizer/event_list.html",
        context,
    )


@organizer_required
def organizer_event_create(request):
    if request.method == "POST":
        form = EventForm(
            request.POST,
            request.FILES,
        )

        if form.is_valid():
            create_draft_event(
                organization=request.active_organization,
                cleaned_data=form.cleaned_data,
            )

            messages.success(
                request,
                "Evento criado como rascunho.",
            )

            return redirect("events:organizer-list")
    else:
        form = EventForm()

    context = {
        "organization": request.active_organization,
        "form": form,
        "page_title": "Criar evento",
        "submit_label": "Salvar rascunho",
    }

    return render(
        request,
        "events/organizer/event_form.html",
        context,
    )


@organizer_required
def organizer_event_update(request, event_id):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    if request.method == "POST":
        form = EventForm(
            request.POST,
            request.FILES,
            instance=event,
        )

        if form.is_valid():
            update_draft_event(
                organization=request.active_organization,
                event_id=event.id,
                cleaned_data=form.cleaned_data,
            )

            messages.success(
                request,
                "Rascunho atualizado com sucesso.",
            )

            return redirect("events:organizer-list")
    else:
        form = EventForm(instance=event)

    context = {
        "organization": request.active_organization,
        "event": event,
        "form": form,
        "page_title": "Editar evento",
        "submit_label": "Salvar alterações",
    }

    return render(
        request,
        "events/organizer/event_form.html",
        context,
    )


@organizer_required
@require_POST
def organizer_event_publish(request, event_id):
    try:
        publish_event(
            organization=request.active_organization,
            event_id=event_id,
        )
    except ValidationError as error:
        messages.error(
            request,
            "Não foi possível publicar: "
            + " ".join(error.messages),
        )
    else:
        messages.success(
            request,
            "Evento publicado com sucesso.",
        )

    return redirect("events:organizer-list")


@organizer_required
@require_POST
def organizer_event_cancel(request, event_id):
    try:
        cancel_event(
            organization=request.active_organization,
            event_id=event_id,
        )
    except ValidationError as error:
        messages.error(
            request,
            "Não foi possível cancelar: "
            + " ".join(error.messages),
        )
    else:
        messages.success(
            request,
            "Evento cancelado com sucesso.",
        )

    return redirect("events:organizer-list")


def _add_validation_errors_to_form(form, error):
    """
    Transfere ValidationError do serviço para o formulário.
    """
    if hasattr(error, "message_dict"):
        for field_name, messages_list in (
            error.message_dict.items()
        ):
            target_field = (
                field_name
                if field_name in form.fields
                else None
            )

            for message_text in messages_list:
                form.add_error(
                    target_field,
                    message_text,
                )
    else:
        form.add_error(None, error)


@organizer_required
def organizer_ticket_configuration(request, event_id):
    event = event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    ticket_types = list(
        ticket_types_for_event(event)
    )

    allocated_capacity = sum(
        ticket_type.capacity
        for ticket_type in ticket_types
        if ticket_type.is_active
    )

    configuration_errors = (
        commercial_configuration_errors(event)
        if event.is_editable
        else []
    )

    context = {
        "organization": request.active_organization,
        "event": event,
        "ticket_types": ticket_types,
        "allocated_capacity": allocated_capacity,
        "available_capacity": max(
            event.capacity - allocated_capacity,
            0,
        ),
        "configuration_errors": configuration_errors,
        "commercial_configuration_ready": (
            not configuration_errors
        ),
    }

    return render(
        request,
        "events/organizer/ticket_configuration.html",
        context,
    )


@organizer_required
def organizer_ticket_type_create(request, event_id):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    if request.method == "POST":
        form = TicketTypeForm(request.POST)

        if form.is_valid():
            try:
                create_ticket_type(
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
                    "Tipo de ingresso criado com sucesso.",
                )

                return redirect(
                    "events:ticket-configuration",
                    event_id=event.id,
                )
    else:
        form = TicketTypeForm()

    context = {
        "organization": request.active_organization,
        "event": event,
        "form": form,
        "page_title": "Criar tipo de ingresso",
        "submit_label": "Salvar tipo de ingresso",
    }

    return render(
        request,
        "events/organizer/commercial_form.html",
        context,
    )


@organizer_required
def organizer_ticket_type_update(
    request,
    event_id,
    ticket_type_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    ticket_type = ticket_type_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        ticket_type_id=ticket_type_id,
    )

    if request.method == "POST":
        form = TicketTypeForm(
            request.POST,
            instance=ticket_type,
        )

        if form.is_valid():
            try:
                update_ticket_type(
                    organization=request.active_organization,
                    event_id=event.id,
                    ticket_type_id=ticket_type.id,
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
                    "Tipo de ingresso atualizado.",
                )

                return redirect(
                    "events:ticket-configuration",
                    event_id=event.id,
                )
    else:
        form = TicketTypeForm(
            instance=ticket_type
        )

    context = {
        "organization": request.active_organization,
        "event": event,
        "ticket_type": ticket_type,
        "form": form,
        "page_title": "Editar tipo de ingresso",
        "submit_label": "Salvar alterações",
    }

    return render(
        request,
        "events/organizer/commercial_form.html",
        context,
    )

@organizer_required
def organizer_ticket_lot_create(
    request,
    event_id,
    ticket_type_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    ticket_type = ticket_type_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        ticket_type_id=ticket_type_id,
    )

    if request.method == "POST":
        form = TicketLotForm(request.POST)

        if form.is_valid():
            try:
                create_ticket_lot(
                    organization=request.active_organization,
                    event_id=event.id,
                    ticket_type_id=ticket_type.id,
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
                    "Lote criado com sucesso.",
                )

                return redirect(
                    "events:ticket-configuration",
                    event_id=event.id,
                )
    else:
        form = TicketLotForm()

    context = {
        "organization": request.active_organization,
        "event": event,
        "ticket_type": ticket_type,
        "form": form,
        "page_title": "Criar lote",
        "submit_label": "Salvar lote",
        "footer_note": (
            f"Capacidade do tipo: {ticket_type.capacity}."
        ),
    }

    return render(
        request,
        "events/organizer/commercial_form.html",
        context,
    )


@organizer_required
def organizer_ticket_lot_update(
    request,
    event_id,
    ticket_type_id,
    ticket_lot_id,
):
    event = editable_event_for_organization_or_404(
        organization=request.active_organization,
        event_id=event_id,
    )

    ticket_type = ticket_type_for_event_or_404(
        organization=request.active_organization,
        event_id=event.id,
        ticket_type_id=ticket_type_id,
    )

    ticket_lot = ticket_lot_for_type_or_404(
        organization=request.active_organization,
        event_id=event.id,
        ticket_type_id=ticket_type.id,
        ticket_lot_id=ticket_lot_id,
    )

    if request.method == "POST":
        form = TicketLotForm(
            request.POST,
            instance=ticket_lot,
        )

        if form.is_valid():
            try:
                update_ticket_lot(
                    organization=request.active_organization,
                    event_id=event.id,
                    ticket_type_id=ticket_type.id,
                    ticket_lot_id=ticket_lot.id,
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
                    "Lote atualizado com sucesso.",
                )

                return redirect(
                    "events:ticket-configuration",
                    event_id=event.id,
                )
    else:
        form = TicketLotForm(
            instance=ticket_lot
        )

    context = {
        "organization": request.active_organization,
        "event": event,
        "ticket_type": ticket_type,
        "ticket_lot": ticket_lot,
        "form": form,
        "page_title": "Editar lote",
        "submit_label": "Salvar alterações",
        "footer_note": (
            f"Capacidade do tipo: {ticket_type.capacity}."
        ),
    }

    return render(
        request,
        "events/organizer/commercial_form.html",
        context,
    )