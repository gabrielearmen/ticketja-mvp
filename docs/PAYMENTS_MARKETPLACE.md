# Pagamentos marketplace — operação segura

O TicketJá utiliza o modelo **Split de Pagamentos 1:1** do Mercado Pago.
Cada organização conecta sua própria conta via OAuth. O PIX é criado com o
Access Token dessa conta e a comissão do TicketJá é enviada como
`application_fee`.

## O que nunca deve ser feito

- pedir senha ou Access Token ao organizador;
- salvar tokens sem criptografia;
- habilitar pagamentos antes de configurar e testar o webhook;
- utilizar o serviço gratuito do Render para operação financeira real;
- colocar segredos no GitHub, em templates, JavaScript ou logs;
- alterar uma política de comissão dentro de um pedido existente.

## Ordem de ativação

1. Use Web Service e PostgreSQL persistentes, com backup e monitoramento.
2. Crie a aplicação Marketplace no Mercado Pago e habilite Authorization
   Code com PKCE.
3. Cadastre exatamente esta Redirect URI na aplicação:
   `https://SEU-DOMINIO/painel/recebimentos/mercado-pago/retorno/`.
4. Gere uma chave Fernet exclusiva:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
5. Configure os segredos no provedor de hospedagem, nunca no `.env.example`.
6. Execute `python manage.py migrate`.
7. Ative somente `MARKETPLACE_OAUTH_ENABLED=true` e mantenha
   `MARKETPLACE_PAYMENTS_ENABLED=false`.
8. Cada proprietário acessa **Painel → Recebimentos** e conecta sua conta.
9. Cadastre a política de comissão com o comando abaixo.
10. No Mercado Pago, configure notificações do tipo pagamento para
    `https://SEU-DOMINIO/webhooks/mercado-pago/payments/` e salve a chave
    em `MERCADO_PAGO_WEBHOOK_SECRET`.
11. Homologue criação, pagamento, repetição de webhook, expiração e
    cancelamento no ambiente de teste.
12. Configure uma tarefa periódica para executar a conciliação financeira.
13. Somente após a homologação, ative
    `MARKETPLACE_PAYMENTS_ENABLED=true`.

## Variáveis protegidas

```text
MARKETPLACE_OAUTH_ENABLED=true
MARKETPLACE_PAYMENTS_ENABLED=false
MARKETPLACE_TOKEN_ENCRYPTION_KEYS=<chave-fernet>
MERCADO_PAGO_CLIENT_ID=<app-id>
MERCADO_PAGO_CLIENT_SECRET=<secret-key>
MERCADO_PAGO_OAUTH_REDIRECT_URI=https://SEU-DOMINIO/painel/recebimentos/mercado-pago/retorno/
MERCADO_PAGO_WEBHOOK_SECRET=<assinatura-do-webhook>
MERCADO_PAGO_TEST_MODE=true
```

Em uma rotação de criptografia, coloque a chave nova primeiro e mantenha a
anterior temporariamente: `chave_nova,chave_anterior`.

## Política de comissão

A política comercial aprovada possui estas regras:

- comissão percentual entre 8% e 10%;
- nenhuma mensalidade;
- nenhum valor fixo por ingresso;
- comprador como responsável padrão pela taxa;
- possibilidade administrativa de o organizador absorver a taxa;
- dados de antifraude e custos do gateway não geram uma linha adicional
  para o comprador;
- pedidos antigos nunca são recalculados quando a política muda.

Política inicial recomendada — 8%, paga pelo comprador:

```powershell
python manage.py configure_marketplace_fee `
    --name "Taxa padrão" `
    --percentage 8 `
    --fixed-per-ticket 0.00 `
    --fee-bearer buyer
```

Cada pedido guarda o identificador da política e os valores calculados no
momento da reserva.

Para uma campanha em que o organizador absorva 10%, crie uma nova versão:

```powershell
python manage.py configure_marketplace_fee `
    --name "Taxa absorvida pelo organizador" `
    --percentage 10 `
    --fixed-per-ticket 0.00 `
    --fee-bearer organizer
```

No MVP, a política é administrada pela plataforma. O organizador não altera
percentual ou responsável pela taxa sem autorização comercial.

## Dados do pagador

Em pedidos pagos, o fluxo é:

`Participantes → Dados do pagador → PIX → Confirmação`.

O pagador pode ser diferente dos participantes. O CPF é validado, armazenado
com criptografia e enviado ao provedor somente pelo backend. O número completo
não aparece em templates, JavaScript, logs, QR Code ou Django Admin. Pedidos
gratuitos não solicitam documento de cobrança.

## Conciliação periódica

O webhook é a confirmação principal. A conciliação consulta diretamente o
Mercado Pago para recuperar notificações atrasadas ou perdidas:

```powershell
python manage.py reconcile_payments --limit 100
```

Em produção, execute o comando a cada cinco minutos. Cobranças abertas podem
ser consultadas a cada cinco minutos; pagamentos já encerrados são limitados a
uma consulta diária, reduzindo tráfego desnecessário. A mesma validação
transacional usada pelo webhook é reutilizada, incluindo conferência de valor,
referência externa, estoque, idempotência e isolamento da organização.

## Reembolsos e contestações

- reembolso e seus custos são responsabilidade do organizador;
- chargeback suspende a inscrição e é registrado como `chargeback`;
- nenhuma notificação recebida é aceita sem consulta posterior ao provedor;
- compensação em eventos futuros ou cobrança direta exige aceite contratual,
  registro financeiro auditável e operação autorizada;
- o TicketJá não executa débito automático oculto em conta do organizador.

## Reversão segura

Defina `MARKETPLACE_PAYMENTS_ENABLED=false`. Isso interrompe a criação de
novas cobranças marketplace sem apagar pedidos, pagamentos, contas conectadas
ou trilhas de webhook já persistidas. Nunca reverta migrações com pagamentos
em andamento.
