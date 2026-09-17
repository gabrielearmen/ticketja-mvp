from django import forms

from apps.events.models import TicketLot


class TicketLotChoiceField(forms.ModelChoiceField):
    """
    Gera um nome compreensível para cada opção comercial.
    """

    def label_from_instance(self, ticket_lot):
        if ticket_lot.is_free:
            formatted_price = "Gratuito"
        else:
            formatted_price = (
                f"R$ {ticket_lot.price:.2f}"
                .replace(".", ",")
            )

        return (
            f"{ticket_lot.ticket_type.name} — "
            f"{ticket_lot.name} — "
            f"{formatted_price}"
        )


class StartCheckoutForm(forms.Form):
    ticket_lot = TicketLotChoiceField(
        label="Ingresso",
        queryset=TicketLot.objects.none(),
        empty_label=None,
        widget=forms.RadioSelect,
        error_messages={
            "required": "Escolha um tipo de ingresso.",
            "invalid_choice": (
                "O ingresso selecionado não pertence "
                "a este evento."
            ),
        },
    )

    quantity = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                "min": "1",
                "step": "1",
                "inputmode": "numeric",
                "autocomplete": "off",
            }
        ),
        error_messages={
            "required": "Informe a quantidade.",
            "invalid": (
                "Informe uma quantidade numérica válida."
            ),
            "min_value": (
                "A quantidade deve ser maior que zero."
            ),
        },
    )

    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
    )

    def __init__(
        self,
        *args,
        event,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.event = event

        self.fields["ticket_lot"].queryset = (
            TicketLot.objects
            .filter(
                ticket_type__event=event,
                ticket_type__is_active=True,
                is_active=True,
            )
            .select_related(
                "ticket_type",
                "ticket_type__event",
                "ticket_type__event__organization",
            )
            .order_by(
                "ticket_type__name",
                "sales_start",
                "price",
                "name",
            )
        )