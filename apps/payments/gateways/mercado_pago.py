import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from .base import (
    PaymentGateway,
    PaymentGatewayConfigurationError,
    PaymentGatewayRejectedError,
    PaymentGatewayTemporaryError,
    PaymentSnapshot,
    PixChargeRequest,
    PixChargeResult,
)


MINIMUM_PIX_EXPIRATION_SECONDS = 30 * 60
MAXIMUM_PIX_EXPIRATION_SECONDS = 30 * 24 * 60 * 60


def _decimal_value(value, *, default="0.00"):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _parse_datetime(value):
    if not value:
        return None

    normalized = str(value).strip()

    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)

    return parsed


def _first_transaction_payment(order_data):
    transactions = order_data.get("transactions") or {}
    payments = transactions.get("payments") or []

    if not payments:
        return {}

    first_payment = payments[0]

    if not isinstance(first_payment, dict):
        return {}

    return first_payment


def _sanitized_provider_message(payload, status_code):
    if isinstance(payload, dict):
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("code")
        )

        if message:
            return (
                f"Mercado Pago recusou a operação "
                f"({status_code}): {str(message)[:300]}"
            )

    return (
        f"Mercado Pago recusou a operação "
        f"com código HTTP {status_code}."
    )


class MercadoPagoGateway(PaymentGateway):
    """
    Integração REST com a Orders API do Mercado Pago.

    Utilizamos somente bibliotecas nativas do Python. Assim,
    não é necessário instalar um SDK adicional nesta fase.
    """

    def __init__(
        self,
        *,
        access_token=None,
        api_base_url=None,
        timeout_seconds=None,
    ):
        self.access_token = (
            access_token
            if access_token is not None
            else settings.MERCADO_PAGO_ACCESS_TOKEN
        ).strip()

        self.api_base_url = (
            api_base_url
            if api_base_url is not None
            else settings.MERCADO_PAGO_API_BASE_URL
        ).strip().rstrip("/")

        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.MERCADO_PAGO_TIMEOUT_SECONDS
        )

        if not self.access_token:
            raise PaymentGatewayConfigurationError(
                "O Access Token do Mercado Pago não foi configurado."
            )

        if not self.api_base_url.startswith("https://"):
            raise PaymentGatewayConfigurationError(
                "O endereço da API do Mercado Pago deve usar HTTPS."
            )

    def _request_json(
        self,
        *,
        method,
        path,
        payload=None,
        idempotency_key=None,
    ):
        url = f"{self.api_base_url}{path}"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": (
                f"Bearer {self.access_token}"
            ),
        }

        if idempotency_key is not None:
            headers["X-Idempotency-Key"] = str(
                idempotency_key
            )

        body = None

        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")

        request = Request(
            url=url,
            data=body,
            headers=headers,
            method=method,
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                response_body = response.read()

        except HTTPError as error:
            raw_body = error.read()

            try:
                error_payload = json.loads(
                    raw_body.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                error_payload = {}

            message = _sanitized_provider_message(
                error_payload,
                error.code,
            )

            if error.code == 429 or error.code >= 500:
                raise PaymentGatewayTemporaryError(
                    message
                ) from error

            raise PaymentGatewayRejectedError(
                message
            ) from error

        except (URLError, TimeoutError) as error:
            raise PaymentGatewayTemporaryError(
                "O Mercado Pago está temporariamente "
                "indisponível. Tente novamente."
            ) from error

        try:
            parsed_body = json.loads(
                response_body.decode("utf-8")
            )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise PaymentGatewayTemporaryError(
                "O Mercado Pago retornou uma resposta inválida."
            ) from error

        if not isinstance(parsed_body, dict):
            raise PaymentGatewayTemporaryError(
                "O Mercado Pago retornou uma resposta inesperada."
            )

        return parsed_body

    def _expiration_duration(
        self,
        expiration_seconds,
    ):
        """
        Produz uma duração estável.

        Repetições com a mesma chave de idempotência precisam
        enviar exatamente o mesmo conteúdo ao provedor.
        """
        if (
            isinstance(expiration_seconds, bool)
            or not isinstance(expiration_seconds, int)
        ):
            raise PaymentGatewayRejectedError(
                "O vencimento do PIX é inválido."
            )

        if (
            expiration_seconds
            < MINIMUM_PIX_EXPIRATION_SECONDS
        ):
            raise PaymentGatewayRejectedError(
                "O vencimento do PIX deve possuir pelo menos "
                "30 minutos."
            )

        if (
            expiration_seconds
            > MAXIMUM_PIX_EXPIRATION_SECONDS
        ):
            raise PaymentGatewayRejectedError(
                "O vencimento do PIX não pode superar 30 dias."
            )

        return f"PT{expiration_seconds}S"

    def create_pix_charge(
        self,
        request: PixChargeRequest,
    ) -> PixChargeResult:
        amount = request.amount.quantize(
            Decimal("0.01")
        )

        payload = {
            "type": "online",
            "total_amount": format(amount, ".2f"),
            "external_reference": (
                request.external_reference
            ),
            "processing_mode": "automatic",
            "transactions": {
                "payments": [
                    {
                        "amount": format(
                            amount,
                            ".2f",
                        ),
                        "payment_method": {
                            "id": "pix",
                            "type": "bank_transfer",
                        },
                        "expiration_time": (
                            self._expiration_duration(
                                request.expiration_seconds
                            )
                        ),
                    }
                ]
            },
            "payer": {
                "email": request.payer_email,
            },
        }

        order_data = self._request_json(
            method="POST",
            path="/v1/orders",
            payload=payload,
            idempotency_key=request.idempotency_key,
        )

        provider_payment = _first_transaction_payment(
            order_data
        )

        payment_method = (
            provider_payment.get("payment_method") or {}
        )

        provider_order_id = str(
            order_data.get("id") or ""
        ).strip()

        provider_payment_id = str(
            provider_payment.get("id") or ""
        ).strip()

        pix_copy_paste = str(
            payment_method.get("qr_code") or ""
        ).strip()

        pix_qr_code_base64 = str(
            payment_method.get("qr_code_base64") or ""
        ).strip()

        checkout_url = str(
            payment_method.get("ticket_url") or ""
        ).strip()

        required_values = {
            "identificador da ordem": provider_order_id,
            "identificador do pagamento": (
                provider_payment_id
            ),
            "código PIX": pix_copy_paste,
            "QR Code PIX": pix_qr_code_base64,
            "endereço de pagamento": checkout_url,
        }

        missing_values = [
            label
            for label, value in required_values.items()
            if not value
        ]

        if missing_values:
            raise PaymentGatewayTemporaryError(
                "A cobrança está sendo processada pelo "
                "Mercado Pago, mas ainda não retornou: "
                + ", ".join(missing_values)
                + ". Repita a consulta com a mesma chave."
            )

        return PixChargeResult(
            provider_order_id=provider_order_id,
            provider_payment_id=provider_payment_id,
            provider_status=str(
                provider_payment.get("status")
                or order_data.get("status")
                or ""
            ),
            provider_status_detail=str(
                provider_payment.get("status_detail")
                or order_data.get("status_detail")
                or ""
            ),
            pix_copy_paste=pix_copy_paste,
            pix_qr_code_base64=pix_qr_code_base64,
            checkout_url=checkout_url,
            expires_at=request.expires_at,
        )

    def _snapshot_from_order(self, order_data):
        provider_payment = _first_transaction_payment(
            order_data
        )

        provider_status = str(
            provider_payment.get("status")
            or order_data.get("status")
            or ""
        )

        provider_status_detail = str(
            provider_payment.get("status_detail")
            or order_data.get("status_detail")
            or ""
        )

        amount = _decimal_value(
            provider_payment.get("amount")
            or order_data.get("total_amount")
        )

        approved_at = None

        if provider_status == "processed":
            approved_at = _parse_datetime(
                order_data.get("last_updated_date")
            )

        return PaymentSnapshot(
            provider_order_id=str(
                order_data.get("id") or ""
            ),
            provider_payment_id=str(
                provider_payment.get("id") or ""
            ),
            provider_status=provider_status,
            provider_status_detail=(
                provider_status_detail
            ),
            amount=amount,
            approved_at=approved_at,
        )

    def fetch_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        normalized_id = quote(
            str(provider_order_id),
            safe="",
        )

        order_data = self._request_json(
            method="GET",
            path=f"/v1/orders/{normalized_id}",
        )

        return self._snapshot_from_order(order_data)

    def cancel_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        normalized_id = quote(
            str(provider_order_id),
            safe="",
        )

        order_data = self._request_json(
            method="POST",
            path=(
                f"/v1/orders/{normalized_id}/cancel"
            ),
            idempotency_key=uuid4(),
        )

        return self._snapshot_from_order(order_data)