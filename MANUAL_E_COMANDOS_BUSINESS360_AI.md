# Manual tecnico e operacional - Business360 AI

Data do registro: 20/07/2026
Sistema: Business360 AI
Empresa base: Deike Equipamentos Ltda
Repositorio: https://github.com/financeirodedike-dotcom/sistema-financeiro-cloud
Servidor VPS: Hostinger Ubuntu 24.04 LTS
Pasta no servidor: /opt/business360/app

---

## 1. Objetivo do sistema

O Business360 AI nasceu a partir da planilha de fluxo de caixa 2026 e foi transformado em um sistema web para centralizar gestao financeira e empresarial.

A ideia principal e sair de uma planilha manual e chegar em uma plataforma simples, robusta e confiavel, com importacao de OFX, classificacao financeira, fluxo de caixa, DRE, endividamento, compras, fiscal, RH, vendas, marketing, producao, mapa empresarial 360 e controle de acessos.

---

## 2. Tecnologias usadas

- Backend: Python com FastAPI.
- Templates: Jinja2 com HTML e CSS.
- Banco local inicial: SQLite.
- Banco em producao: PostgreSQL.
- ORM: SQLAlchemy.
- Importacao bancaria: leitor OFX proprio.
- Hospedagem inicial: Render.
- Hospedagem atual: VPS Hostinger KVM com Docker.
- Deploy: Docker Compose.
- Controle de versao: Git e GitHub.

---

## 3. Estrutura principal do projeto

```text
sistema_financeiro_cloud/
  app/
    main.py              # Rotas, regras principais, telas e acoes do sistema
    database.py          # Conexao com banco de dados
    models.py            # Tabelas do banco via SQLAlchemy
    schemas.py           # Estruturas auxiliares de validacao
    ofx_parser.py        # Leitor de arquivos OFX
    classifier.py        # Classificacao automatica por palavras-chave
    reports.py           # Relatorios financeiros e gerenciais
    auth.py              # Login, senha e sessao
    templates/
      index.html         # Tela principal do sistema
      login.html         # Login
      register.html      # Cadastro inicial
      forgot_password.html # Esqueci minha senha
  data/
    .gitkeep
  Dockerfile             # Imagem da aplicacao
  docker-compose.yml     # Servicos Docker: web e banco
  requirements.txt       # Dependencias Python
  README.md              # Apresentacao rapida do projeto
  DEPLOY.md              # Instrucao inicial de deploy
  run_local.cmd          # Execucao local no Windows
```

---

## 4. Modulos criados ou estruturados

### Centro de Controle

Painel inicial com visao executiva do negocio:

- receitas;
- despesas;
- resultado;
- lancamentos sem classificacao;
- leitura rapida do caixa;
- ultimas importacoes;
- grafico de entradas e saidas por mes;
- despesas por grupo;
- endividamento;
- tarefas e agenda operacional planejada.

### Financeiro

Modulo central do sistema. Dentro dele foram criadas ou planejadas as seguintes abas:

- Extratos;
- Cadastros bancarios;
- Classificacao;
- Contabilizados;
- Fluxo de Caixa;
- DRE;
- Balanco;
- Endividamento;
- Contas a pagar;
- Contas a receber;
- Antecipacoes.

### Extratos

Funcionalidades:

- importar arquivos OFX;
- ler banco, agencia e conta vindos do OFX;
- cadastrar banco/agencia/conta automaticamente quando vier no arquivo;
- evitar duplicidade de lancamentos importados;
- pesquisar historico;
- pesquisar por data;
- filtrar por banco/caixa interno;
- classificar lancamento;
- contabilizar em lote;
- permitir rateio em mais de uma conta financeira;
- depois de contabilizado, retirar da lista de pendentes e enviar para Contabilizados.

### Contabilizados

Criado para separar o que ja foi classificado do que ainda precisa ser tratado.

Funcionalidades:

- listar lancamentos ja contabilizados;
- agrupar por conta financeira;
- expandir o grupo para ver os lancamentos;
- pesquisar por data;
- pesquisar por conta financeira.

### Classificacao

Funcionalidades:

- cadastrar contas financeiras;
- padronizar contas em caixa alta;
- remover duplicadas mantendo versoes corretas com acento;
- criar regras por palavra-chave;
- usar regras para classificar automaticamente lancamentos OFX.

### Fluxo de Caixa

Foi pedido para seguir o modelo da planilha de fluxo de caixa projetado, com:

- realizado;
- planejado/orcado;
- saldo inicial;
- entradas;
- saidas;
- saldo do periodo;
- saldo acumulado;
- totalizadores por mes;
- sobra/falta operacional;
- bancos;
- captacao bancaria;
- pagamentos de emprestimos;
- investimentos;
- sobra/falta acumulada.

Formula de conciliacao solicitada:

```text
Saldo inicial + Entradas - Saidas = Saldo final calculado
Saldo final informado pelo banco = X
Diferenca de conciliacao = Y
```

Tambem foi solicitado puxar saldo inicial e saldo final diretamente do OFX quando o arquivo trouxer essas informacoes.

### DRE

Melhorias solicitadas:

- deixar mais profissional;
- agrupar receitas, custos, despesas, financeiro e resultado;
- usar padrao brasileiro de moeda;
- ajudar tomada de decisao.

### Endividamento

Funcionalidades criadas e ajustadas:

- cadastro de dividas e emprestimos;
- data da divida;
- vencimento;
- dias em atraso;
- tipo do credor: fornecedor, banco ou pessoa fisica;
- capital;
- taxa mensal;
- juros simples ou compostos;
- parcelas/pagamentos;
- saldo atualizado;
- painel superior de resumo;
- clicar na linha da divida atualiza o painel;
- clicar fora volta para o total da empresa;
- gerar evolucao da divida mes a mes;
- gerar evolucao ate hoje quando nao houver vencimento;
- gerar evolucao ate o vencimento quando houver vencimento;
- botao para registrar pagamento;
- opcao de movimentar ou nao em Contabilizados;
- opcao de vincular pagamento a lancamento OFX;
- impressao do relatorio da evolucao da divida;
- totalizadores no final do endividamento e no relatorio de evolucao.

Campos do relatorio de evolucao:

```text
Mes
Descricao
Data do desconto / inicio
Vencimento
Dias
Valor
Taxa
Ao dia
Total de juros
Total a pagar
Observacoes
```

Ajuste importante feito:

- Removida a coluna Valor do credito no relatorio de evolucao.
- Ajustado o relatorio de impressao para imprimir apenas o relatorio, sem botoes, menus, formularios e textos duplicados.

### Antecipacoes

Funcionalidades solicitadas:

- cadastrar empresa ou pessoa fisica que antecipou;
- taxa sobre valor dos titulos;
- juros;
- IOF;
- custas;
- valor final antecipado;
- anexar arquivos relacionados: foto de cheque, PDF, comprovantes e outros.

### Contas a receber

Solicitado criar modelo semelhante a planilha enviada, com:

- data de vencimento;
- cliente;
- plano de conta;
- descricao;
- nota fiscal/recibo/pedido;
- parcela;
- conta;
- status;
- data de quitacao;
- valor da parcela;
- valor total da conta;
- desconto;
- juros;
- dias em atraso;
- total da parcela;
- resumo de recebidas, em aberto, vencidas, descontos e juros.

Tambem solicitado:

- botao para antecipar titulos;
- simulador de antecipacao;
- informar empresa/pessoa que descontou o titulo;
- informar valor antecipado final ou percentual de juros pagos.

### Contas a pagar

Criado/planejado dentro do Financeiro para controle de boletos, vencimentos e pagamentos.

### Fiscal

Solicitado:

- aba Fiscal;
- leitor/importador de XML;
- organizacao de notas fiscais para integracao futura.

### RH

Solicitado dentro de RH:

- cadastro de colaborador;
- cadastro de EPI;
- exames periodicos;
- treinamentos;
- descritivo de funcao;
- cartao ponto;
- controle de ferias;
- controle de atestados;
- salarios e custo total para empresa.

### Vendas

Solicitado:

- cadastro de produto;
- cadastro de cliente;
- futuramente pedidos, margem e acompanhamento comercial.

### Marketing

Solicitado:

- planejamento de marketing com calendario;
- investimento;
- retorno sobre investimento ROI;
- CAC.

### Producao

Solicitado:

- aba Producao;
- dentro dela, PCP.

### Mapa Empresarial 360

Solicitado:

- mapa empresarial conforme blueprint Business360AI;
- visao integrada dos setores;
- calendario na parte inferior.

### Acessos e Usuarios

Solicitado:

- aba de gerenciamento de acessos e usuarios;
- redefinir senha;
- tela de entrada com opcao Esqueci minha senha.

---

## 5. Padroes financeiros definidos

- Moeda no padrao brasileiro: R$ 1.234,56.
- Datas no padrao brasileiro: dd/mm/aaaa.
- Contas financeiras em caixa alta.
- Duplicadas devem ser corrigidas e padronizadas.
- Lancamento classificado deve mudar de status/cor e sair da pendencia.
- Lancamento contabilizado deve aparecer na aba Contabilizados.

---

## 6. Lista base de contas financeiras

As contas financeiras devem ser padronizadas em caixa alta, removendo duplicadas e mantendo acentuacao correta quando existir.

Exemplos principais:

```text
VENDA A VISTA
VENDA A PRAZO ANTECIPADAS
VENDAS REFORMA
VENDA DE SERVICO
VENDA DE SUCATA
VENDA IMOBILIZADO
MATERIA PRIMA
MATERIAL DE CONSUMO
ALUGUEL DO IMOVEL
ENERGIA ELETRICA
AGUA
TELEFONIA MOVEL
INTERNET
LOCACAO DE SOFTWARE
HONORARIOS ADVOCATICIOS
HONORARIOS CONTABEIS
COMBUSTIVEIS
PEDAGIO
MANUTENCAO DE VEICULOS
SEGUROS DE VEICULOS
IPVA
LICENCIAMENTO ANUAL
FINANCIAMENTO STRADA
MATERIAL DE ESCRITORIO
MATERIAL DE LIMPEZA
DIARISTA / LIMPEZA
ALIMENTACAO / MERCADO
FRETE COMPRAS
MANUTENCAO EMPRESA
MANUTENCAO MAQUINAS E EQUIPAMENTOS
MOVEIS E UTENSILIOS
ESTACIONAMENTO
SERASA
HOSPEDAGEM SITE
CERTIFICADO DIGITAL
FERRAMENTAS
EQUIPAMENTOS DE T.I.
MARKETING
COMISSAO
FRETE VENDAS
SIMPLES NACIONAL DAS
SERVICOS TERCEIRIZADOS
SALARIO
DESPESA AJUDA DE CUSTO
DESPESA VALE COMPRA / TRANSPORTE
HORAS EXTRAS
13 SALARIO
FERIAS FUNCIONARIOS
DESPESA RESCISAO
DESPESA MULTA RESCISAO 40% FGTS
DESPESA ASSISTENCIA MEDICA / PLANO DE SAUDE
FARMACIA
INSS
FGTS
DESPESA IRRF SALARIOS
DESPESA UNIFORMES
DESPESA MEDICINA OCUPACIONAL
EPI
DESPESA BONUS PONTUALIDADE
DESPESA ENDOMARKETING
DEPOSITO JUDICIAL TRABALHISTA
TARIFAS BANCARIAS
BORDERO
JUROS ANTECIPACOES DE TITULOS
JUROS POR ATRASO
JUROS LIMITE
JUROS EMPRESTIMOS
TAXA CARTAO CREDITO/DEBITO
IOF
ROTATIVO CRESOL
TARIFA FLAT BB
```

---

## 7. Hospedagem e infraestrutura

### Render

Foi usado inicialmente para subir o sistema com:

- Web Service;
- PostgreSQL;
- variavel DATABASE_URL;
- ajuste do driver psycopg para PostgreSQL.

Problema encontrado:

```text
ModuleNotFoundError: No module named 'psycopg2'
```

Solucao aplicada:

- usar driver psycopg/URL compativel com SQLAlchemy.

### Hostinger VPS

Foi contratada VPS e configurada com:

- localizacao Brasil;
- Ubuntu 24.04 LTS;
- acesso SSH root;
- Docker;
- Docker Compose;
- firewall UFW com portas 22, 80 e 443;
- aplicacao em /opt/business360/app;
- PostgreSQL em container;
- web em container.

Comando SSH usado:

```bash
ssh root@179.197.71.19
```

Portas liberadas:

```text
OpenSSH ALLOW Anywhere
80/tcp  ALLOW Anywhere
443/tcp ALLOW Anywhere
```

---

## 8. Comandos principais do servidor

### Entrar no servidor

No PowerShell do Windows:

```powershell
ssh root@179.197.71.19
```

### Ir para a pasta do sistema

Dentro do SSH:

```bash
cd /opt/business360/app
```

### Ver containers

```bash
docker compose ps
```

### Subir ou atualizar containers

```bash
docker compose up -d --build
```

### Ver logs do sistema

```bash
docker compose logs --tail=50 web
```

### Parar containers

```bash
docker compose down
```

### Reiniciar somente o sistema web

```bash
docker compose restart web
```

### Script de atualizacao do sistema

O comando correto deve ser rodado dentro do SSH do VPS, nao no PowerShell local:

```bash
/opt/business360/atualizar-business360.sh
```

Erro comum quando roda no PowerShell local:

```text
O termo '/opt/business360/atualizar-business360.sh' nao e reconhecido...
```

Explicacao: `/opt/business360/...` e caminho Linux do servidor. No Windows esse caminho nao existe. Primeiro precisa entrar no SSH.

---

## 9. Docker Compose usado no VPS

Modelo de `docker-compose.yml` com PostgreSQL e Web:

```yaml
services:
  db:
    image: postgres:16
    container_name: business360-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: business360
      POSTGRES_USER: business360
      POSTGRES_PASSWORD: troque-esta-senha-do-banco
    volumes:
      - business360_postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U business360 -d business360"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    build: .
    container_name: business360-web
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://business360:troque-esta-senha-do-banco@db:5432/business360
      APP_NAME: Business360 AI
      APP_ENV: production
      SECRET_KEY: troque-esta-chave-por-uma-frase-grande-e-secreta
    ports:
      - "8000:8000"

volumes:
  business360_postgres:
```

---

## 10. Backup

Foi criado backup automatico via cron.

Linha do cron:

```bash
0 3 * * * /opt/business360/backup-business360.sh >> /opt/business360/backups/backup.log 2>&1
```

Significado:

- roda todos os dias as 03:00;
- salva log em `/opt/business360/backups/backup.log`.

Ver cron instalado:

```bash
crontab -l
```

Pasta esperada dos backups:

```bash
/opt/business360/backups
```

---

## 11. Importacao OFX e prevencao de duplicidade

Regra definida:

- o sistema registra cada lote importado;
- usa identificador bancario do OFX para evitar duplicidade;
- se importar o mesmo arquivo ou mesmo mes novamente, deve ignorar lancamentos repetidos;
- quando o OFX trouxer banco, agencia e conta, o sistema deve usar essas informacoes para cadastrar ou reconhecer a origem.

Campos importantes do OFX:

```text
Banco
Agencia
Conta
Data do lancamento
Historico
Valor
Identificador unico do banco
Saldo inicial
Saldo final
```

Validacao desejada:

```text
Saldo inicial + Entradas - Saidas = Saldo final calculado
Saldo final informado pelo banco = saldo final do OFX
Diferenca de conciliacao = saldo final OFX - saldo final calculado
```

---

## 12. Erros encontrados e solucoes

### Erro: senha SSH negada

Mensagem:

```text
Permission denied, please try again.
```

Causa:

- senha root digitada incorretamente.

Solucao:

- copiar senha correta do painel da Hostinger;
- tentar novamente.

### Erro: comando Linux rodado no PowerShell local

Mensagem:

```text
/opt/business360/atualizar-business360.sh nao e reconhecido
```

Causa:

- comando do servidor foi executado no Windows.

Solucao:

```powershell
ssh root@179.197.71.19
```

Depois, dentro do servidor:

```bash
/opt/business360/atualizar-business360.sh
```

### Erro: script com caractere inesperado

Mensagem:

```text
-bash: syntax error near unexpected token '|'
```

Causa possivel:

- conteudo do script ficou com caractere quebrado;
- colagem incompleta;
- linha copiada com simbolo indevido.

Solucao:

- abrir o script com nano;
- corrigir a linha;
- salvar novamente.

### Erro: pg_dump versao diferente

Mensagem:

```text
server version: 18.x; pg_dump version: 16.x
```

Causa:

- tentativa de backup do banco Render com versao PostgreSQL 18 usando cliente 16.

Solucao usada:

```bash
docker run --rm postgres:18 pg_dump --no-owner --no-privileges "$RENDER_DB_URL" > render_backup.sql
```

---

## 13. Fluxo de trabalho com GitHub

### Clonar repositorio no servidor

```bash
mkdir -p /opt/business360
cd /opt/business360
git clone https://github.com/financeirodedike-dotcom/sistema-financeiro-cloud.git app
cd /opt/business360/app
```

### Atualizar codigo no VPS

```bash
cd /opt/business360/app
git pull
docker compose up -d --build
docker compose logs --tail=50 web
```

### Publicar alteracoes feitas localmente

No ambiente local de desenvolvimento, as alteracoes sao commitadas e enviadas para o GitHub.

Exemplo:

```bash
git add app/templates/index.html app/main.py app/models.py app/reports.py
git commit -m "Descricao da melhoria"
git push -u origin main
```

Depois no VPS:

```bash
/opt/business360/atualizar-business360.sh
```

---

## 14. Melhorias visuais realizadas ou solicitadas

- identidade Business360 AI;
- cabecalho azul;
- menu superior restaurado apos teste com menu lateral;
- dashboard mais profissional;
- cards executivos;
- paineis com indicadores;
- tabelas mais limpas;
- botoes de impressao;
- impressao limpa apenas do relatorio;
- formato brasileiro de datas e moeda.

---

## 15. Proximos passos recomendados

1. Revisar fluxo de caixa projetado com base na planilha original.
2. Finalizar conciliacao usando saldo inicial e final do OFX.
3. Melhorar performance das telas com muitos lancamentos.
4. Criar paginacao nas tabelas grandes.
5. Criar filtros persistentes por data, banco e conta.
6. Fechar modulo de Contas a Receber com antecipacao de titulos.
7. Fechar Contas a Pagar com agenda e boletos da semana.
8. Melhorar permissoes por usuario e perfil.
9. Configurar HTTPS com dominio definitivo.
10. Configurar n8n no mesmo VPS ou em container separado para automacoes futuras.
11. Criar rotina de backup externo fora da VPS.
12. Criar relatorio PDF para endividamento, DRE e fluxo de caixa.

---

## 16. Comandos rapidos de rotina

### Acessar servidor

```powershell
ssh root@179.197.71.19
```

### Atualizar sistema no servidor

```bash
/opt/business360/atualizar-business360.sh
```

### Ver se esta rodando

```bash
cd /opt/business360/app
docker compose ps
```

### Ver logs

```bash
cd /opt/business360/app
docker compose logs --tail=50 web
```

### Reiniciar sistema

```bash
cd /opt/business360/app
docker compose restart web
```

### Fazer backup manual

```bash
/opt/business360/backup-business360.sh
```

---

## 17. Observacao final

Este arquivo registra o que foi construido, decidido e corrigido ate aqui. Ele deve ser atualizado sempre que o sistema receber uma melhoria importante, principalmente em banco de dados, importacao OFX, regras financeiras, deploy e backup.
