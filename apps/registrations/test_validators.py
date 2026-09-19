from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .validators import (
    normalize_and_validate_phone,
    normalize_document_number,
    validate_cpf,
)


class RegistrationValidatorTests(SimpleTestCase):
    def test_valid_cpf_is_accepted_and_normalized(self):
        self.assertEqual(
            validate_cpf("529.982.247-25"),
            "52998224725",
        )

    def test_invalid_cpf_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cpf("529.982.247-24")

    def test_repeated_cpf_is_rejected(self):
        with self.assertRaises(ValidationError):
            validate_cpf("111.111.111-11")

    def test_cpf_document_is_normalized_to_digits(self):
        self.assertEqual(
            normalize_document_number(
                document_type="cpf",
                document_number="529.982.247-25",
            ),
            "52998224725",
        )

    def test_passport_is_normalized_to_uppercase(self):
        self.assertEqual(
            normalize_document_number(
                document_type="passaporte",
                document_number="  br 123456  ",
            ),
            "BR 123456",
        )

    def test_phone_is_normalized_to_digits(self):
        self.assertEqual(
            normalize_and_validate_phone(
                "(85) 99999-9999"
            ),
            "85999999999",
        )

    def test_invalid_phone_is_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_and_validate_phone("123")