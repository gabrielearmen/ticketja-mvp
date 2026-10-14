import json
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from django.conf import settings
from django.utils import timezone

from .base import (
    HostedCheckoutRequest,
    HostedCheckoutResult,
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
MERCADO_PAGO_CHECKOUT_HOSTS = (
    "mercadopago.com",
    "mercadopago.com.br",
)


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


def _format_mercado_pago_datetime(value):
    """
    Formata datas para o padrão ISO 8601 aceito pela Payments API.

    O Mercado Pago exige timezone explícito e precisão máxima
    de milissegundos no campo date_of_expiration.
    """
    if not isinstance(value, datetime):
        raise PaymentGatewayRejectedError(
            "A data de vencimento do PIX é inválida."
        )

    if timezone.is_naive(value):
        value = timezone.make_aware(
            value,
            datetime_timezone.utc,
        )

    return value.astimezone(datetime_timezone.utc).isoformat(
        timespec="milliseconds"
    )


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


def _money_string(value):
    return format(
        Decimal(value).quantize(Decimal("0.01")),
        ".2f",
    )


def _is_mercado_pago_checkout_url(value):
    parsed = urlparse(str(value or "").strip())
    hostname = (parsed.hostname or "").lower()

    return (
        parsed.scheme == "https"
        and any(
            hostname == allowed
            or hostname.endswith(f".{allowed}")
            for allowed in MERCADO_PAGO_CHECKOUT_HOSTS
        )
    )


class MercadoPagoGateway(PaymentGateway):
    """
    Integração REST com as APIs de Payments e Orders.

    No Checkout Pro com Split 1:1, o Access Token OAuth pertence
    ao organizador e a comissão do TicketJá usa marketplace_fee.
    """

    def __init__(
        self,
        *,
        access_token=None,
        api_base_url=None,
        timeout_seconds=None,
        use_orders_api=False,
    ):
        self.use_orders_api = bool(use_orders_api)
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
        self._expiration_duration(
            request.expiration_seconds
        )
        amount = request.amount.quantize(
            Decimal("0.01")
        )

        payer = {
            "email": request.payer_email,
        }

        if settings.MERCADO_PAGO_TEST_MODE:
            payer["first_name"] = "APRO"
            payer["last_name"] = request.payer_last_name or "Teste"
        elif request.payer_first_name and request.payer_last_name:
            payer["first_name"] = request.payer_first_name
            payer["last_name"] = request.payer_last_name

        if (
            request.payer_document_type
            and request.payer_document_number
        ):
            payer["identification"] = {
                "type": request.payer_document_type,
                "number": request.payer_document_number,
            }

        payload = {
            "transaction_amount": float(amount),
            "description": request.description,
            "payment_method_id": "pix",
            "external_reference": request.external_reference,
            "date_of_expiration": _format_mercado_pago_datetime(
                request.expires_at
            ),
            "payer": payer,
        }

        platform_fee = request.platform_fee.quantize(
            Decimal("0.01")
        )

        if platform_fee > Decimal("0.00"):
            payload["application_fee"] = float(platform_fee)

        payment_data = self._request_json(
            method="POST",
            path="/v1/payments",
            payload=payload,
            idempotency_key=request.idempotency_key,
        )

        provider_payment_id = str(
            payment_data.get("id") or ""
        ).strip()
        provider_order_id = provider_payment_id
        point_of_interaction = (
            payment_data.get("point_of_interaction") or {}
        )
        transaction_data = (
            point_of_interaction.get("transaction_data") or {}
        )

        pix_copy_paste = str(
            transaction_data.get("qr_code") or ""
        ).strip()

        pix_qr_code_base64 = str(
            transaction_data.get("qr_code_base64") or ""
        ).strip()

        checkout_url = str(
            transaction_data.get("ticket_url") or ""
        ).strip()

        required_values = {
            "identificador da ordem": provider_order_id,
            "identificador do pagamento": (
                provider_payment_id
            ),
            "código PIX": pix_copy_paste,
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
                payment_data.get("status") or ""
            ),
            provider_status_detail=str(
                payment_data.get("status_detail") or ""
            ),
            pix_copy_paste=pix_copy_paste,
            pix_qr_code_base64=pix_qr_code_base64,
            checkout_url=checkout_url,
            expires_at=request.expires_at,
        )

    def create_hosted_checkout(
        self,
        request: HostedCheckoutRequest,
    ) -> HostedCheckoutResult:
        expiration_time = self._expiration_duration(
            request.expiration_seconds
        )

        if not request.items:
            raise PaymentGatewayRejectedError(
                "O checkout precisa possuir ao menos um item."
            )

        items = []
        calculated_total = Decimal("0.00")

        for item in request.items:
            if item.quantity < 1:
                raise PaymentGatewayRejectedError(
                    "A quantidade de um item do checkout é inválida."
                )

            unit_price = item.unit_price.quantize(
                Decimal("0.01")
            )

            if unit_price < Decimal("0.00"):
                raise PaymentGatewayRejectedError(
                    "O valor de um item do checkout é inválido."
                )

            item_total = unit_price * item.quantity
            calculated_total += item_total
            items.append(
                {
                    "title": item.title[:255],
                    "quantity": item.quantity,
                    "unit_price": _money_string(unit_price),
                    "unit_measure": "unit",
                    "total_amount": _money_string(item_total),
                }
            )

        amount = request.amount.quantize(Decimal("0.01"))

        if calculated_total.quantize(Decimal("0.01")) != amount:
            raise PaymentGatewayRejectedError(
                "A soma dos itens diverge do total do checkout."
            )

        payload = {
            "type": "online",
            "processing_mode": "manual",
            "capture_mode": "automatic_async",
            "total_amount": _money_string(amount),
            "external_reference": request.external_reference,
            "description": request.description[:255],
            "expiration_time": expiration_time,
            "payer": {
                "email": request.payer_email,
            },
            "items": items,
            "config": {
                "online": {
                    "success_url": request.success_url,
                    "pending_url": request.pending_url,
                    "failure_url": request.failure_url,
                    "auto_return": "all",
                }
            },
        }

        platform_fee = request.platform_fee.quantize(
            Decimal("0.01")
        )

        if platform_fee > Decimal("0.00"):
            payload["marketplace_fee"] = _money_string(
                platform_fee
            )

        order_data = self._request_json(
            method="POST",
            path="/v1/orders",
            payload=payload,
            idempotency_key=request.idempotency_key,
        )

        provider_order_id = str(
            order_data.get("id") or ""
        ).strip()
        checkout_url = str(
            order_data.get("checkout_url") or ""
        ).strip()

        if not provider_order_id:
            raise PaymentGatewayTemporaryError(
                "O Mercado Pago não retornou o identificador da ordem."
            )

        if not _is_mercado_pago_checkout_url(checkout_url):
            raise PaymentGatewayTemporaryError(
                "O Mercado Pago não retornou um endereço de checkout válido."
            )

        return HostedCheckoutResult(
            provider_order_id=provider_order_id,
            provider_status=str(
                order_data.get("status") or ""
            ),
            provider_status_detail=str(
                order_data.get("status_detail") or ""
            ),
            checkout_url=checkout_url,
            expires_at=request.expires_at,
        )

    def _snapshot_from_payment(self, payment_data):
        provider_status = str(
            payment_data.get("status") or ""
        )

        provider_status_detail = str(
            payment_data.get("status_detail") or ""
        )

        amount = _decimal_value(
            payment_data.get("transaction_amount")
        )

        approved_at = None

        if provider_status == "approved":
            approved_at = _parse_datetime(
                payment_data.get("date_approved")
            )

        fee_details = payment_data.get("fee_details") or []
        provider_fee = sum(
            (
                _decimal_value(item.get("amount"))
                for item in fee_details
                if isinstance(item, dict)
                and str(item.get("type") or "").lower()
                != "application_fee"
            ),
            Decimal("0.00"),
        )
        transaction_details = (
            payment_data.get("transaction_details") or {}
        )
        net_amount = _decimal_value(
            transaction_details.get("net_received_amount")
        )
        payment_id = str(payment_data.get("id") or "").strip()

        return PaymentSnapshot(
            provider_order_id=payment_id,
            provider_payment_id=payment_id,
            provider_status=provider_status,
            provider_status_detail=provider_status_detail,
            amount=amount,
            approved_at=approved_at,
            provider_fee=provider_fee,
            net_amount=net_amount,
            external_reference=str(
                payment_data.get("external_reference") or ""
            ).strip(),
        )

    def _snapshot_from_order(self, order_data):
        provider_payment = _first_transaction_payment(order_data)
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
            provider_order_id=str(order_data.get("id") or "").strip(),
            provider_payment_id=str(
                provider_payment.get("id") or ""
            ).strip(),
            provider_status=provider_status,
            provider_status_detail=provider_status_detail,
            amount=amount,
            approved_at=approved_at,
            external_reference=str(
                order_data.get("external_reference") or ""
            ).strip(),
        )

    def fetch_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        normalized_id = quote(
            str(provider_order_id),
            safe="",
        )

        if self.use_orders_api:
            order_data = self._request_json(
                method="GET",
                path=f"/v1/orders/{normalized_id}",
            )
            return self._snapshot_from_order(order_data)

        payment_data = self._request_json(
            method="GET",
            path=f"/v1/payments/{normalized_id}",
        )

        return self._snapshot_from_payment(payment_data)

    def cancel_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        normalized_id = quote(
            str(provider_order_id),
            safe="",
        )

        if self.use_orders_api:
            order_data = self._request_json(
                method="POST",
                path=f"/v1/orders/{normalized_id}/cancel",
                idempotency_key=uuid4(),
            )
            return self._snapshot_from_order(order_data)

        payment_data = self._request_json(
            method="PUT",
            path=f"/v1/payments/{normalized_id}",
            payload={"status": "cancelled"},
            idempotency_key=uuid4(),
        )

        return self._snapshot_from_payment(payment_data)
