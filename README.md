# TicketJá

Plataforma web para organização, divulgação e inscrição em eventos esportivos.

O TicketJá está sendo desenvolvido com Django e PostgreSQL, priorizando segurança, isolamento de dados entre organizações, acessibilidade, desempenho e uma experiência simples para participantes e organizadores.

> Este projeto está em desenvolvimento. A versão atual é um MVP e ainda não está pronta para operação comercial em produção.

## Visão do produto

O TicketJá pretende centralizar o fluxo completo de eventos esportivos:

- criação e administração de eventos;
- publicação e descoberta de eventos;
- configuração de modalidades, ingressos e lotes;
- compra de múltiplos ingressos;
- inscrição de participantes diferentes do comprador;
- pagamento;
- emissão de credenciais;
- validação por QR Code;
- check-in com suporte a funcionamento offline;
- acompanhamento de inscrições pelo organizador.

## Estado atual do MVP

### Funcionalidades implementadas

#### Contas e autenticação

- cadastro de usuário;
- autenticação utilizando e-mail e senha;
- armazenamento seguro de senhas pelo Django;
- ativação de conta por e-mail;
- tratamento de tokens inválidos ou reutilizados;
- login sem diferenciação entre letras maiúsculas e minúsculas no e-mail;
- logout por requisição POST;
- bloqueio de login para contas inativas;
- recuperação e alteração de senha;
- painel básico do usuário.

#### Organizações

- cadastro de organizações;
- situação de organização pendente, aprovada ou suspensa;
- associação de usuários às organizações;
- papéis de proprietário e administrador;
- seleção da organização ativa;
- isolamento de dados entre organizações;
- bloqueio de acesso para usuários sem organização autorizada;
- painel do organizador.

#### Eventos

- criação de evento como rascunho;
- edição de eventos em rascunho;
- publicação de eventos;
- cancelamento de eventos publicados;
- upload de imagem de capa;
- validação de formato e tamanho da capa;
- definição de modalidade esportiva;
- definição de data, horário, cidade, estado e endereço;
- definição da capacidade total;
- proteção contra acesso a eventos de outra organização;
- bloqueio de alterações comerciais depois da publicação;
- exibição pública somente de eventos publicados e futuros.

#### Ingressos e lotes

- criação de tipos de ingresso;
- descrição e capacidade por tipo;
- ativação e desativação de tipos;
- criação de lotes;
- preço por lote;
- suporte a lotes gratuitos;
- quantidade máxima por lote;
- início e encerramento das vendas;
- identificação de lote programado, em venda ou encerrado;
- validação da capacidade total do evento;
- validação da capacidade dos tipos de ingresso;
- validação da quantidade distribuída entre lotes;
- bloqueio de períodos de venda sobrepostos;
- bloqueio de lotes com término posterior ao evento;
- validação da configuração comercial antes da publicação.

#### Interface pública

- Landing Page para descoberta de eventos;
- pesquisa por nome, descrição ou modalidade;
- pesquisa por cidade ou estado;
- cards responsivos de eventos;
- página pública de detalhes do evento;
- apresentação da capa, modalidade, descrição, data e endereço;
- identificação da organização responsável;
- apresentação de tipos de ingresso;
- apresentação do lote comercial relevante;
- apresentação do preço e período de venda;
- estados visuais para vendas abertas, programadas ou encerradas;
- interface responsiva em dispositivos móveis;
- navegação por teclado e elementos HTML semânticos.

#### Qualidade

- testes automatizados de autenticação;
- testes de cadastro e ativação;
- testes de autorização;
- testes de isolamento entre organizações;
- testes do ciclo de vida dos eventos;
- testes das regras de capacidade;
- testes de lotes e períodos comerciais;
- testes da Landing Page;
- PostgreSQL utilizado no desenvolvimento e nos testes;
- validações de integridade também aplicadas no banco de dados.

## Funcionalidades ainda não implementadas

As funcionalidades abaixo fazem parte do planejamento, mas não devem ser consideradas concluídas:

- seleção da quantidade de ingressos;
- criação de pedidos;
- reservas temporárias de estoque;
- expiração automática de reservas;
- cadastro dos participantes de cada ingresso;
- checkout;
- cálculo de taxas comerciais;
- integração com meio de pagamento;
- confirmação automática de pagamento;
- cancelamento e reembolso;
- área de pedidos do comprador;
- área de inscrições do participante;
- gestão de participantes pelo organizador;
- emissão de ingresso ou credencial;
- geração de QR Code;
- validação de credenciais;
- check-in;
- sincronização de check-in offline;
- relatórios financeiros;
- relatórios operacionais;
- notificações transacionais;
- infraestrutura definitiva de produção.

O botão **“Inscrever-se”** da página pública atualmente direciona o usuário até a apresentação dos tipos de ingresso. A criação efetiva de pedido e reserva será conectada nas próximas etapas.

## Tecnologias utilizadas

- Python 3.14
- Django 5.2
- PostgreSQL
- Psycopg 3
- Pillow
- python-dotenv
- HTML semântico
- CSS responsivo
- Git e GitHub

## Arquitetura do projeto

```text
TicketJa/
├── apps/
│   ├── accounts/          # Usuários, autenticação e conta
│   ├── core/              # Landing Page e elementos gerais
│   ├── events/            # Eventos, tipos de ingresso e lotes
│   └── organizations/     # Organizações, membros e isolamento
├── config/                # Configurações centrais do Django
├── static/                # CSS, imagens e arquivos estáticos
├── templates/             # Templates HTML
├── .env.example           # Exemplo das variáveis de ambiente
├── .gitignore             # Arquivos que não devem ir ao Git
├── manage.py              # Comandos administrativos do Django
├── README.md              # Documentação principal
└── requirements.txt       # Dependências do projeto
```

## Requisitos para executar no Windows

Antes de instalar o projeto, o computador precisa possuir:

- Python;
- PostgreSQL;
- Git;
- um editor como o Visual Studio Code.

A versão atual foi desenvolvida e testada com:

```text
Python 3.14.6
Django 5.2.17
PostgreSQL 18.4
```

## Como instalar e executar no Windows

### 1. Baixar o projeto

Substitua a URL abaixo pela URL real do repositório:

```powershell
git clone https://github.com/SEU-USUARIO/TicketJa.git
cd TicketJa
```

### 2. Criar o ambiente virtual

```powershell
py -m venv .venv
```

O ambiente virtual mantém as bibliotecas do projeto isoladas das demais instalações do computador.

### 3. Ativar o ambiente virtual

```powershell
.\.venv\Scripts\Activate.ps1
```

Quando estiver ativo, o PowerShell apresentará:

```text
(.venv) PS C:\caminho\do\projeto\TicketJa>
```

### 4. Instalar as dependências

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 5. Criar o usuário e os bancos no PostgreSQL

Entre no PostgreSQL com um usuário administrador:

```powershell
psql -U postgres -h localhost -p 5432 -d postgres
```

Se o `psql` não estiver configurado no PATH, utilize o caminho correspondente à versão instalada. Exemplo:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -h localhost -p 5432 -d postgres
```

Dentro do `psql`, crie o usuário da aplicação:

```sql
CREATE USER ticketja_app WITH PASSWORD 'defina-uma-senha-local-segura';
```

Crie o banco de desenvolvimento:

```sql
CREATE DATABASE ticketja OWNER ticketja_app;
```

Crie o banco de testes:

```sql
CREATE DATABASE ticketja_test OWNER ticketja_app;
```

Saia do PostgreSQL:

```sql
\q
```

As senhas utilizadas localmente não devem ser colocadas no GitHub.

### 6. Criar o arquivo de configuração local

Copie o exemplo:

```powershell
Copy-Item .env.example .env
```

Abra o arquivo `.env` e configure:

```text
DJANGO_SECRET_KEY=adicione-uma-chave-secreta
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=ticketja
POSTGRES_TEST_DB=ticketja_test
POSTGRES_USER=ticketja_app
POSTGRES_PASSWORD=senha-definida-no-postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

Uma chave segura para o Django pode ser gerada com:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copie o resultado para `DJANGO_SECRET_KEY`.

O arquivo `.env` é local e nunca deve ser enviado ao GitHub.

### 7. Verificar a configuração

```powershell
python manage.py check
```

Resultado esperado:

```text
System check identified no issues (0 silenced).
```

### 8. Criar as tabelas no PostgreSQL

```powershell
python manage.py migrate
```

Esse comando aplica as migrações e cria a estrutura necessária no banco.

### 9. Criar um administrador

Esta etapa é opcional, mas necessária para acessar o Django Admin:

```powershell
python manage.py createsuperuser
```

Informe o e-mail e uma senha segura quando solicitado.

### 10. Executar os testes

```powershell
python manage.py test --keepdb
```

Resultado esperado ao final:

```text
OK
```

O banco `ticketja_test` é utilizado para evitar que os testes alterem os dados de desenvolvimento.

### 11. Iniciar o servidor

```powershell
python manage.py runserver
```

Abra no navegador:

```text
http://127.0.0.1:8000/
```

O painel administrativo ficará disponível em:

```text
http://127.0.0.1:8000/admin/
```

## Rotas principais

### Área pública

```text
/                         Landing Page
/eventos/<event_id>/      Detalhes públicos do evento
```

### Painel do organizador

```text
/painel/                  Painel da organização
/painel/eventos/          Gestão de eventos
/painel/eventos/novo/     Criação de evento
```

### Administração

```text
/admin/                   Django Admin
```

Algumas rotas exigem autenticação e associação com uma organização aprovada.

## Variáveis de ambiente

| Variável | Finalidade |
|---|---|
| `DJANGO_SECRET_KEY` | Chave criptográfica utilizada pelo Django |
| `DJANGO_DEBUG` | Controla o modo de desenvolvimento |
| `DJANGO_ALLOWED_HOSTS` | Define os endereços autorizados |
| `POSTGRES_DB` | Banco principal |
| `POSTGRES_TEST_DB` | Banco exclusivo dos testes |
| `POSTGRES_USER` | Usuário da aplicação no PostgreSQL |
| `POSTGRES_PASSWORD` | Senha local do PostgreSQL |
| `POSTGRES_HOST` | Servidor do banco |
| `POSTGRES_PORT` | Porta do PostgreSQL |

## Arquivos que não são enviados ao GitHub

O `.gitignore` impede o envio de:

- `.env`;
- `.venv`;
- caches do Python;
- bancos SQLite;
- imagens enviadas localmente;
- logs;
- arquivos temporários;
- configurações pessoais de editores.

Isso significa que o repositório contém o código e as migrações, mas não contém senhas, dados pessoais, banco local ou arquivos enviados por usuários.

## Segurança implementada

- senhas não são armazenadas em texto puro;
- autenticação baseada no sistema seguro do Django;
- ativação de conta com token;
- erros de login não revelam se um e-mail está cadastrado;
- logout executado por POST;
- proteção CSRF nos formulários;
- UUIDs utilizados como identificadores principais;
- consultas privadas filtradas pela organização ativa;
- acesso cruzado entre organizações retorna erro;
- alterações comerciais restritas aos estados permitidos;
- validações na aplicação e no PostgreSQL;
- rascunhos e eventos cancelados não são expostos publicamente;
- eventos de organizações não aprovadas não devem ser exibidos;
- segredos mantidos fora do código-fonte.

## Banco de dados e arquivos locais

O PostgreSQL não é enviado ao GitHub.

Ao baixar o projeto em outro computador, será necessário:

1. instalar o PostgreSQL;
2. criar os bancos;
3. configurar o `.env`;
4. executar as migrações;
5. cadastrar os dados daquele ambiente.

A pasta `media` também não é versionada. Em produção, as imagens deverão ser armazenadas em um serviço apropriado de armazenamento de arquivos.

## Execução de verificações

Antes de enviar alterações ao repositório, execute:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test --keepdb
```

O envio só deve ser realizado quando todas as verificações forem concluídas com sucesso.

## Fluxo sugerido de desenvolvimento

Para novas funcionalidades:

1. atualizar o código;
2. criar ou atualizar os testes;
3. verificar se há migrações;
4. aplicar as migrações;
5. executar todos os testes;
6. revisar os arquivos alterados;
7. criar um commit descritivo;
8. enviar ao GitHub.

Exemplo de commit:

```powershell
git commit -m "feat: adiciona página pública de eventos"
```

## Próximas etapas técnicas

A sequência planejada de desenvolvimento é:

1. testes da página pública do evento;
2. pedidos;
3. reservas temporárias;
4. controle de disponibilidade;
5. participantes;
6. checkout;
7. integração de pagamento;
8. área de pedidos do comprador;
9. gestão de inscrições pelo organizador;
10. credenciais e QR Code;
11. check-in;
12. check-in offline;
13. preparação de produção;
14. auditoria de segurança e proteção de dados.

## Uso e propriedade

Este é um projeto privado, destinado exclusivamente à equipe e aos responsáveis autorizados pelo TicketJá.

A definição formal de propriedade intelectual, licenciamento, tratamento de dados e responsabilidades comerciais deverá ser estabelecida pela empresa responsável antes da disponibilização pública.