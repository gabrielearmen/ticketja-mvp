import re

from django.core.exceptions import ValidationError


def only_digits(value):
    return re.sub(r"\D", "", value or "")


def normalize_document_number(
    *,
    document_type,
    document_number,
):
    value = (document_number or "").strip()

    if document_type == "cpf":
        return only_digits(value)

    return " ".join(value.upper().split())


def validate_cpf(value):
    """
    Valida quantidade, repetição e dígitos verificadores do CPF.

    O retorno contém apenas os 11 números.
    """
    cpf = only_digits(value)

    if len(cpf) != 11:
        raise ValidationError(
            "Informe um CPF com 11 números."
        )

    if cpf == cpf[0] * 11:
        raise ValidationError(
            "Informe um CPF válido."
        )

    for digit_index in (9, 10):
        total = sum(
            int(cpf[index])
            * (digit_index + 1 - index)
            for index in range(digit_index)
        )

        check_digit = (total * 10) % 11

        if check_digit == 10:
            check_digit = 0

        if check_digit != int(cpf[digit_index]):
            raise ValidationError(
                "Informe um CPF válido."
            )

    return cpf


def normalize_and_validate_phone(value):
    """
    Armazena somente números.

    Aceita números brasileiros e internacionais entre
    10 e 15 dígitos.
    """
    if not value:
        return ""

    phone = only_digits(value)

    if not 10 <= len(phone) <= 15:
        raise ValidationError(
            "Informe um telefone com DDD válido."
        )

    return phone