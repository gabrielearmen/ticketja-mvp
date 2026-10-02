from django import forms

from apps.events.models import TicketType

from .models import EventKit, KitOption


class EventKitForm(forms.ModelForm):
    ticket_types = forms.ModelMultipleChoiceField(
        label="Tipos de ingresso",
        queryset=TicketType.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text=(
            "Selecione os tipos de ingresso que dão direito a este kit."
        ),
        error_messages={
            "required": "Selecione pelo menos um tipo de ingresso.",
            "invalid_choice": (
                "Um dos tipos de ingresso selecionados não pertence "
                "a este evento."
            ),
        },
    )

    class Meta:
        model = EventKit
        fields = (
            "name",
            "description",
            "is_required",
            "is_active",
            "ticket_types",
        )
        labels = {
            "name": "Nome do kit",
            "description": "Conteúdo do kit",
            "is_required": "Escolha obrigatória",
            "is_active": "Kit ativo",
        }
        help_texts = {
            "name": "Exemplo: Kit Corrida 5 km.",
            "description": (
                "Descreva tudo o que será entregue ao participante."
            ),
            "is_required": (
                "Quando marcado, o participante deverá selecionar uma "
                "opção antes de concluir o pedido."
            ),
            "is_active": (
                "Kits inativos permanecem no histórico, mas não são "
                "oferecidos ao participante."
            ),
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: Kit Corrida 5 km",
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 5,
                    "placeholder": (
                        "Ex.: camiseta, número de peito, medalha..."
                    ),
                }
            ),
            "is_required": forms.CheckboxInput(
                attrs={"class": "form-checkbox"}
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-checkbox"}
            ),
        }

    def __init__(self, *args, event, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)

        self.fields["ticket_types"].queryset = (
            TicketType.objects.filter(event=event)
            .order_by("name", "id")
        )

        self.fields["ticket_types"].widget.attrs.update(
            {"class": "kit-ticket-types"}
        )

        if self.instance.pk and not self.is_bound:
            self.initial["ticket_types"] = list(
                self.instance.ticket_types.values_list("pk", flat=True)
            )


class KitOptionForm(forms.ModelForm):
    class Meta:
        model = KitOption
        fields = (
            "name",
            "stock_quantity",
            "is_active",
        )
        labels = {
            "name": "Tamanho ou variação",
            "stock_quantity": "Quantidade em estoque",
            "is_active": "Opção ativa",
        }
        help_texts = {
            "name": (
                "Exemplos: P, M, G, GG, cor azul ou sem tamanho."
            ),
            "stock_quantity": (
                "Quantidade máxima disponível desta opção."
            ),
            "is_active": (
                "Opções inativas permanecem no histórico e não poderão "
                "ser escolhidas."
            ),
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ex.: M",
                    "autocomplete": "off",
                }
            ),
            "stock_quantity": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": 1,
                    "step": 1,
                    "inputmode": "numeric",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={"class": "form-checkbox"}
            ),
        }