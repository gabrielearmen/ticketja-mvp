import hashlib
import hmac
import re
from dataclasses import dataclass


SHA256_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


class WebhookSignatureError(Exception):
    """
    A notificação não possui uma assinatura válida.
    """


@dataclass(frozen=True, slots=True)
class WebhookSignature:
    timestamp: str
    digest: str


def _parse_signature_header(value):
    timestamp = ""
    digests = []

    for raw_part in str(value or "").split(","):
        key, separator, raw_value = raw_part.strip().partition("=")

        if not separator:
            continue

        normalized_key = key.strip().lower()
        normalized_value = raw_value.strip()

        if normalized_key == "ts":
            timestamp = normalized_value

        elif normalized_key == "v1":
            digests.append(normalized_value)

    if not timestamp or not timestamp.isdigit():
        raise WebhookSignatureError(
            "Timestamp ausente ou inválido."
        )

    valid_digests = [
        digest.lower()
        for digest in digests
        if SHA256_HEX_PATTERN.fullmatch(digest)
    ]

    if not valid_digests:
        raise WebhookSignatureError(
            "Assinatura ausente ou inválida."
        )

    return timestamp, valid_digests


def validate_mercado_pago_signature(
    *,
    secret,
    signature_header,
    request_id,
    data_id,
):
    """
    Valida a assinatura HMAC-SHA256 enviada pelo Mercado Pago.

    Manifest oficial:
    id:<data.id>;request-id:<x-request-id>;ts:<ts>;
    """
    normalized_secret = str(secret or "").strip()
    normalized_request_id = str(request_id or "").strip()
    normalized_data_id = str(data_id or "").strip()

    if not normalized_secret:
        raise WebhookSignatureError(
            "A chave do webhook não foi configurada."
        )

    if not normalized_request_id:
        raise WebhookSignatureError(
            "O x-request-id não foi informado."
        )

    if not normalized_data_id:
        raise WebhookSignatureError(
            "O data.id não foi informado."
        )

    timestamp, received_digests = (
        _parse_signature_header(signature_header)
    )

    manifest = (
        f"id:{normalized_data_id};"
        f"request-id:{normalized_request_id};"
        f"ts:{timestamp};"
    )

    expected_digest = hmac.new(
        normalized_secret.encode("utf-8"),
        manifest.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    signature_is_valid = any(
        hmac.compare_digest(
            expected_digest,
            received_digest,
        )
        for received_digest in received_digests
    )

    if not signature_is_valid:
        raise WebhookSignatureError(
            "A assinatura do webhook é inválida."
        )

    return WebhookSignature(
        timestamp=timestamp,
        digest=expected_digest,
    )