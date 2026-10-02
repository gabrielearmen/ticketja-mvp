from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseModelFormSet
from django.forms import modelformset_factory

from .models import Registration


PARTICIPANT_FIELD_NAMES = (
    "full_name",
    "document_type",
    "document_number",
    "birth_date",
    "email",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
)


class RegistrationParticipantForm(forms.ModelForm):
    class Meta:
        model = Registration

        fields = PARTICIPANT_FIELD_NAMES

        labels = {
            "full_name": "Nome completo",
            "document_type": "Tipo de documento",
            "document_number": "Número do documento",
            "birth_date": "Data de nascimento",
            "email": "E-mail do participante",
            "phone": "Telefone do participante",
            "emergency_contact_name": (
                "Nome do contato de emergência"
            ),
            "emergency_contact_phone": (
                "Telefone de emergência"
            ),
        }

        help_texts = {
            "email": (
                "Opcional. O comprovante principal será enviado "
                "à conta do comprador."
            ),
            "phone": "Opcional.",
            "emergency_contact_name": (
                "Preencha os dois campos de emergência ou "
                "deixe ambos vazios."
            ),
        }

        widgets = {
            "full_name": forms.TextInput(
                attrs={"autocomplete": "name"}
            ),
            "document_type": forms.Select(),
            "document_number": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "inputmode": "text",
                }
            ),
            "birth_date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={
                    "type": "date",
                    "autocomplete": "bday",
                },
            ),
            "email": forms.EmailInput(
                attrs={"autocomplete": "email"}
            ),
            "phone": forms.TextInput(
                attrs={
                    "autocomplete": "tel",
                    "inputmode": "tel",
                }
            ),
            "emergency_contact_name": forms.TextInput(
                attrs={"autocomplete": "off"}
            ),
            "emergency_contact_phone": forms.TextInput(
                attrs={
                    "autocomplete": "off",
                    "inputmode": "tel",
                }
            ),
        }

    def __init__(
        self,
        *args,
        kit_catalog_by_ticket_type=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.fields["full_name"].required = True
        self.fields["document_type"].required = True
        self.fields["document_number"].required = True
        self.fields["birth_date"].required = True

        self.fields["birth_date"].input_formats = (
            "%Y-%m-%d",
        )

        for field_name in PARTICIPANT_FIELD_NAMES:
            self.fields[
                field_name
            ].widget.attrs["class"] = "form-control"

        self._kit_choice_field_names = []
        self._kit_by_field_name = {}

        if (
            self.instance is None
            or self.instance.pk is None
            or self.instance.order_item_id is None
        ):
            return

        catalog = kit_catalog_by_ticket_type or {}

        ticket_type_id = (
            self.instance.order_item.ticket_type_id
        )

        applicable_kits = catalog.get(
            ticket_type_id,
            (),
        )

        existing_selections = {
            selection.kit_id: selection.option_id
            for selection in (
                self.instance.kit_selections.all()
            )
        }

        for kit_entry in applicable_kits:
            kit = kit_entry.kit

            field_name = f"kit_{kit.id.hex}"

            current_option_id = existing_selections.get(
                kit.id
            )

            empty_choice = (
                "Selecione uma opção"
                if kit.is_required
                else "Não desejo este kit"
            )

            choices = [
                ("", empty_choice),
            ]

            for option_row in kit_entry.option_rows:
                is_current_option = (
                    option_row.option.id
                    == current_option_id
                )

                if (
                    option_row.available_quantity <= 0
                    and not is_current_option
                ):
                    continue

                if (
                    is_current_option
                    and option_row.available_quantity <= 0
                ):
                    availability_label = (
                        "reservada para este participante"
                    )
                elif option_row.available_quantity == 1:
                    availability_label = "1 disponível"
                else:
                    availability_label = (
                        f"{option_row.available_quantity} "
                        "disponíveis"
                    )

                choices.append(
                    (
                        str(option_row.option.id),
                        (
                            f"{option_row.option.name} — "
                            f"{availability_label}"
                        ),
                    )
                )

            help_parts = []

            if kit.description:
                help_parts.append(kit.description)

            if kit.is_required:
                help_parts.append(
                    "A escolha deste kit é obrigatória."
                )
            else:
                help_parts.append(
                    "Este kit é opcional."
                )

            if len(choices) == 1:
                help_parts.append(
                    "Nenhuma opção possui estoque disponível."
                )
            else:
                help_parts.append(
                    "Opções sem estoque não são exibidas."
                )

            kit_field = forms.ChoiceField(
                label=kit.name,
                choices=choices,
                required=kit.is_required,
                help_text=" ".join(help_parts),
                error_messages={
                    "required": (
                        "Selecione uma opção para este kit."
                    ),
                    "invalid_choice": (
                        "A opção selecionada não está mais "
                        "disponível."
                    ),
                },
                widget=forms.Select(
                    attrs={
                        "class": "form-control",
                        "data-kit-choice": "",
                    }
                ),
            )

            kit_field.kit_id = kit.id
            kit_field.kit_description = kit.description
            kit_field.kit_is_required = kit.is_required
            kit_field.has_available_options = (
                len(choices) > 1
            )

            self.fields[field_name] = kit_field
            self._kit_choice_field_names.append(
                field_name
            )
            self._kit_by_field_name[field_name] = kit

            if current_option_id is not None:
                self.initial[field_name] = str(
                    current_option_id
                )

    @property
    def participant_fields(self):
        return [
            self[field_name]
            for field_name in PARTICIPANT_FIELD_NAMES
        ]

    @property
    def kit_choice_fields(self):
        return [
            self[field_name]
            for field_name
            in self._kit_choice_field_names
        ]

    def kit_selection_payload(self):
        """
        Converte os campos dinâmicos para a estrutura esperada
        pelo serviço transacional.
        """

        selections = []

        for field_name in (
            self._kit_choice_field_names
        ):
            kit = self._kit_by_field_name[field_name]

            option_id = self.cleaned_data.get(
                field_name
            )

            selections.append(
                {
                    "kit_id": kit.id,
                    "option_id": option_id or None,
                }
            )

        return selections


class BaseRegistrationParticipantFormSet(
    BaseModelFormSet
):
    """
    Impede que o comprador remova, duplique ou substitua IDs
    de participantes no POST.
    """

    def __init__(self, *args, **kwargs):
        queryset = kwargs.get("queryset")

        self.expected_ids = set()

        if queryset is not None:
            self.expected_ids = {
                str(registration_id)
                for registration_id in (
                    queryset.values_list(
                        "id",
                        flat=True,
                    )
                )
            }

        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()

        if any(self.errors):
            return

        submitted_ids = []

        for form in self.forms:
            registration = form.cleaned_data.get("id")

            if registration is None:
                raise ValidationError(
                    "A lista de participantes é inválida."
                )

            submitted_ids.append(
                str(registration.id)
            )

        if len(submitted_ids) != len(set(submitted_ids)):
            raise ValidationError(
                "Um participante foi enviado mais de uma vez."
            )

        if set(submitted_ids) != self.expected_ids:
            raise ValidationError(
                "A lista de participantes foi alterada."
            )


RegistrationParticipantFormSet = modelformset_factory(
    Registration,
    form=RegistrationParticipantForm,
    formset=BaseRegistrationParticipantFormSet,
    extra=0,
    can_delete=False,
)