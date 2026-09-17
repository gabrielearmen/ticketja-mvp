from django import forms
from django.utils import timezone

from .models import Event, TicketLot, TicketType

class EventForm(forms.ModelForm):
    class Meta:
        model = Event

        fields = (
            "title",
            "summary",
            "sport_category",
            "event_datetime",
            "city",
            "state",
            "address",
            "capacity",
            "cover_image",
        )

        labels = {
            "title": "Nome do evento",
            "summary": "Descrição resumida",
            "sport_category": "Modalidade esportiva",
            "event_datetime": "Data e horário",
            "city": "Cidade",
            "state": "Estado",
            "address": "Endereço",
            "capacity": "Capacidade total",
            "cover_image": "Imagem de capa",
        }

        help_texts = {
            "summary": "Apresente o evento em até 500 caracteres.",
            "capacity": (
                "Informe o número máximo de participantes."
            ),
            "cover_image": (
                "JPG, PNG ou WEBP, com no máximo 5 MB. "
                "A capa será obrigatória para publicar."
            ),
        }

        widgets = {
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: Corrida TicketJá 10K",
                    "autocomplete": "off",
                }
            ),
            "summary": forms.Textarea(
                attrs={
                    "rows": 5,
                    "maxlength": 500,
                    "placeholder": (
                        "Descreva brevemente a experiência do evento."
                    ),
                }
            ),
            "sport_category": forms.Select(),
            "event_datetime": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "type": "datetime-local",
                },
            ),
            "city": forms.TextInput(
                attrs={
                    "autocomplete": "address-level2",
                }
            ),
            "state": forms.Select(
                attrs={
                    "autocomplete": "address-level1",
                }
            ),
            "address": forms.TextInput(
                attrs={
                    "autocomplete": "street-address",
                }
            ),
            "capacity": forms.NumberInput(
                attrs={
                    "min": 1,
                    "inputmode": "numeric",
                }
            ),
            "cover_image": forms.ClearableFileInput(
                attrs={
                    "accept": "image/jpeg,image/png,image/webp",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["event_datetime"].input_formats = (
            "%Y-%m-%dT%H:%M",
        )

        for field in self.fields.values():
            current_class = field.widget.attrs.get("class", "")

            field.widget.attrs["class"] = (
                f"form-control {current_class}"
            ).strip()

    def clean_event_datetime(self):
        event_datetime = self.cleaned_data["event_datetime"]

        if event_datetime <= timezone.now():
            raise forms.ValidationError(
                "Informe uma data e um horário futuros."
            )

        return event_datetime


class TicketTypeForm(forms.ModelForm):
    class Meta:
        model = TicketType

        fields = (
            "name",
            "description",
            "capacity",
            "is_active",
        )

        labels = {
            "name": "Nome do ingresso",
            "description": "Descrição",
            "capacity": "Capacidade",
            "is_active": "Disponível para venda",
        }

        help_texts = {
            "name": (
                "Ex.: Corrida 5 km, Corrida 10 km ou Kit premium."
            ),
            "description": (
                "Explique resumidamente o que esta categoria inclui."
            ),
            "capacity": (
                "Número máximo de inscrições desta categoria."
            ),
            "is_active": (
                "Tipos inativos não poderão receber novos lotes."
            ),
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: Corrida 10 km",
                    "autocomplete": "off",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "maxlength": 300,
                }
            ),
            "capacity": forms.NumberInput(
                attrs={
                    "min": 1,
                    "inputmode": "numeric",
                }
            ),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs["class"] = "form-checkbox"
            else:
                field.widget.attrs["class"] = "form-control"

class TicketLotForm(forms.ModelForm):
    class Meta:
        model = TicketLot

        fields = (
            "name",
            "price",
            "quantity",
            "sales_start",
            "sales_end",
            "is_active",
        )

        labels = {
            "name": "Nome do lote",
            "price": "Preço",
            "quantity": "Quantidade",
            "sales_start": "Início das vendas",
            "sales_end": "Encerramento das vendas",
            "is_active": "Lote ativo",
        }

        help_texts = {
            "name": "Ex.: Primeiro lote ou Lote promocional.",
            "price": (
                "Utilize 0,00 para um ingresso gratuito."
            ),
            "quantity": (
                "Quantidade máxima que este lote poderá vender."
            ),
            "sales_start": (
                "Momento em que o lote ficará disponível."
            ),
            "sales_end": (
                "Deve ser anterior à realização do evento."
            ),
            "is_active": (
                "Lotes inativos não aparecem no checkout."
            ),
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Ex.: Primeiro lote",
                    "autocomplete": "off",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "min": "0",
                    "step": "0.01",
                    "inputmode": "decimal",
                    "placeholder": "0,00",
                }
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "min": 1,
                    "inputmode": "numeric",
                }
            ),
            "sales_start": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "type": "datetime-local",
                },
            ),
            "sales_end": forms.DateTimeInput(
                format="%Y-%m-%dT%H:%M",
                attrs={
                    "type": "datetime-local",
                },
            ),
            "is_active": forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        datetime_input_formats = (
            "%Y-%m-%dT%H:%M",
        )

        self.fields["sales_start"].input_formats = (
            datetime_input_formats
        )

        self.fields["sales_end"].input_formats = (
            datetime_input_formats
        )

        for field_name, field in self.fields.items():
            if field_name == "is_active":
                field.widget.attrs["class"] = "form-checkbox"
            else:
                field.widget.attrs["class"] = "form-control"

    def clean(self):
        cleaned_data = super().clean()

        sales_start = cleaned_data.get("sales_start")
        sales_end = cleaned_data.get("sales_end")
        is_active = cleaned_data.get("is_active")

        if (
            sales_start
            and sales_end
            and sales_start >= sales_end
        ):
            self.add_error(
                "sales_end",
                (
                    "O encerramento deve ser posterior ao "
                    "início das vendas."
                ),
            )

        if (
            is_active
            and sales_end
            and sales_end <= timezone.now()
        ):
            self.add_error(
                "sales_end",
                (
                    "Um lote ativo deve possuir encerramento "
                    "de vendas futuro."
                ),
            )

        return cleaned_data