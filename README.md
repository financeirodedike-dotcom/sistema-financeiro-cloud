# Sistema Financeiro Cloud

Base para transformar o prototipo da planilha em um sistema web robusto.

## Objetivo

Sistema para:

- criar cadastro e login de usuario;
- separar os dados por empresa;
- importar arquivos OFX;
- classificar contas financeiras por regras;
- revisar lancamentos;
- gerar dashboard, fluxo de caixa e DRE gerencial;
- manter dados em banco relacional;
- hospedar em nuvem com Docker, PostgreSQL e backup.

## Arquitetura

- Backend: FastAPI
- Banco de dados: SQLite no desenvolvimento local e PostgreSQL em producao
- ORM: SQLAlchemy
- Frontend: HTML/Jinja inicial, evoluivel para React/Next.js
- Deploy: Docker em Render, Railway, Fly.io, VPS ou AWS/GCP/Azure
- Seguranca inicial: senha com PBKDF2 e sessao por cookie assinado

## Estrutura

```text
sistema_financeiro_cloud/
  app/
    main.py
    database.py
    models.py
    schemas.py
    ofx_parser.py
    classifier.py
    reports.py
    auth.py
    templates/
      index.html
      login.html
      register.html
  data/
    .gitkeep
  requirements.txt
  Dockerfile
  docker-compose.yml
  .env.example
  DEPLOY.md
  run_local.cmd
```

## Como rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Acesse:

```text
http://127.0.0.1:8000
```

No Windows, tambem pode executar:

```bat
run_local.cmd
```

## O que ja existe

- cadastro e login de usuario;
- criacao da primeira empresa;
- separacao dos dados por empresa;
- cadastro de contas financeiras;
- cadastro de regras por palavra-chave;
- importacao OFX pelo navegador;
- historico de importacoes OFX;
- bloqueio de duplicidade por identificador bancario;
- classificacao automatica dos lancamentos importados;
- revisao manual de classificacao;
- dashboard resumido;
- fluxo de caixa mensal;
- DRE gerencial;
- estrutura pronta para Docker.

## Proximos passos

1. Criar recuperacao de senha.
2. Permitir mais usuarios na mesma empresa.
3. Trocar SQLite por PostgreSQL em producao.
4. Criar tela completa de classificacao em lote.
5. Criar exportacao Excel/CSV.
6. Criar backups automaticos.
7. Publicar em nuvem.

