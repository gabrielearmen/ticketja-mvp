from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


class PaymentGatewayError(Exception):
    """
    Erro base de comunicação com um provedor de pagamento.
    """


class PaymentGatewayConfigurationError(
    PaymentGatewayError
):
    """
    Configuração ausente ou inválida.
    """


class PaymentGatewayTemporaryError(PaymentGatewayError):
    """
    Falha temporária que permite repetir a mesma operação.
    """


class PaymentGatewayRejectedError(PaymentGatewayError):
    """
    Requisição definitivamente recusada pelo provedor.
    """


@dataclass(frozen=True, slots=True)
class PixChargeRequest:
    payment_id: UUID
    idempotency_key: UUID
    external_reference: str
    description: str
    amount: Decimal
    platform_fee: Decimal
    payer_email: str
    expires_at: datetime
    expiration_seconds: int = 1800
    provider_account_reference: str = ""
    payer_first_name: str = ""
    payer_last_name: str = ""
    payer_document_type: str = ""
    payer_document_number: str = ""


@dataclass(frozen=True, slots=True)
class PixChargeResult:
    provider_order_id: str
    provider_payment_id: str
    provider_status: str
    provider_status_detail: str
    pix_copy_paste: str
    pix_qr_code_base64: str
    checkout_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class HostedCheckoutItem:
    title: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class HostedCheckoutRequest:
    payment_id: UUID
    idempotency_key: UUID
    external_reference: str
    description: str
    amount: Decimal
    platform_fee: Decimal
    payer_email: str
    expires_at: datetime
    expiration_seconds: int
    success_url: str
    pending_url: str
    failure_url: str
    items: tuple[HostedCheckoutItem, ...]
    provider_account_reference: str = ""


@dataclass(frozen=True, slots=True)
class HostedCheckoutResult:
    provider_order_id: str
    provider_status: str
    provider_status_detail: str
    checkout_url: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    provider_order_id: str
    provider_payment_id: str
    provider_status: str
    provider_status_detail: str
    amount: Decimal
    approved_at: datetime | None = None
    provider_fee: Decimal | None = None
    net_amount: Decimal | None = None
    external_reference: str = ""

class PaymentGateway(ABC):
    """
    Contrato utilizado pela camada de serviços do TicketJá.

    Nenhuma regra de negócio deve acessar diretamente o SDK ou a
    API específica do Mercado Pago.
    """

    @abstractmethod
    def create_pix_charge(
        self,
        request: PixChargeRequest,
    ) -> PixChargeResult:
        raise NotImplementedError

    def create_hosted_checkout(
        self,
        request: HostedCheckoutRequest,
    ) -> HostedCheckoutResult:
        """
        Cria uma sessão de checkout fora do TicketJá.

        Não é abstrato para preservar compatibilidade com gateways
        antigos durante a migração controlada do PIX direto.
        """
        raise NotImplementedError

    @abstractmethod
    def fetch_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        raise NotImplementedError

    @abstractmethod
    def cancel_payment(
        self,
        provider_order_id: str,
    ) -> PaymentSnapshot:
        raise NotImplementedError
