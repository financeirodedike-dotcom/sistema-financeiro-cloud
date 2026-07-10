# Deploy em nuvem

Este projeto foi preparado para rodar em qualquer provedor que aceite Docker.

## Opcao simples: Render/Railway/Fly.io

1. Envie a pasta para um repositorio Git.
2. Crie um servico web usando o `Dockerfile`.
3. Configure as variaveis de ambiente:

```text
APP_ENV=production
DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/banco
SECRET_KEY=uma-chave-longa-gerada-com-seguranca
```

4. Adicione um banco PostgreSQL no provedor.
5. Publique o servico.

## Com Docker local

```bash
docker compose up --build
```

Depois acesse:

```text
http://127.0.0.1:8000
```

## Pontos obrigatorios antes de producao

1. Recuperacao de senha.
2. Convite de novos usuarios para a empresa.
3. PostgreSQL em vez de SQLite.
4. Backup automatico do banco.
5. Monitoramento de erro e logs.
6. Permissoes por perfil: dono, financeiro e leitura.

