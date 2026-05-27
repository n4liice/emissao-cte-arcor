# RPA — Emissão de CT-e (Arcor / Bagley)

Worker RPA que automatiza a emissão de CT-es no TMS ESL Cloud (mandalog.eslcloud.com.br).  
Expõe uma API REST (FastAPI) consumida pelo N8N.

---

## Fluxo de automação

```
ETAPA 1 — Importar XML
  1. Navegar para tela de Fretes
  2. Abrir dropdown Nova Importação
  3. Clicar em TXT - Notas
  4. Aguardar modal
  5. Selecionar Cliente
  6. Selecionar Filial
  6.5. Preencher OC (no modal)
  7. Upload do arquivo TXT
  8. Salvar

ETAPA 2 — Gerar Frete
  9.  Confirmar modal de atenção
  10. Tratar popup intermediário
  11. Garantir "Importar documentos"
  12. Aguardar página do lote
  13. Extrair número do lote
  14. Aba Documentos Importados
  15. Selecionar todos os documentos
  16. Processar
  17. Confirmar geração dos fretes
  18. Aguardar processamento
  19. Aba Fretes

ETAPA 3 — Preencher dados
  20. Corrigir fretes Inconsistentes (se houver) → vira Pendente
  21. Preencher OC / PBR / Natureza conforme tipo_operacao

ETAPA 4 — Gerar CT-e
  22. Selecionar todos os fretes Pendentes
  23. Clicar em Gerar CT-es
  24. Confirmar emissão
  25. Aguardar processamento
  26. Verificar status final
```

---

## Tipos de operação

| `tipo_operacao` | O que faz no frete |
|---|---|
| `TRANSFERENCIA` | Preenche OC + PBR (se informado) |
| `COLETA DE PBR` | Preenche OC + muda Natureza → `PALETES` + Classificação → `COLETA DE PALETES` |

---

## API

### `POST /importar`

Executa o fluxo completo para um arquivo TXT.

**Body:**
```json
{
  "customer_id": "0",
  "items": [
    {
      "filename": "754NOT631010.B.txt",
      "numero_oc": "52165588",
      "tipo_operacao": "TRANSFERENCIA",
      "numero_pbr": null,
      "xml": "<conteúdo do arquivo TXT>"
    }
  ]
}
```

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `customer_id` | string | Sim | ID do cliente (usar `"0"` para lookup por nome) |
| `customer_name` | string | Não | Default: `"BAGLEY CPS"` |
| `corporation_id` | string | Não | Default: `"MANDALOG OPERACOES E LOGISTICAS"` |
| `items[].filename` | string | Sim | Nome do arquivo TXT |
| `items[].numero_oc` | string | Sim | Número da Ordem de Compra |
| `items[].tipo_operacao` | string | Não | `"TRANSFERENCIA"` (default) ou `"COLETA DE PBR"` |
| `items[].numero_pbr` | string | Não | Número do PBR (apenas para TRANSFERENCIA) |
| `items[].xml` | string | Sim | Conteúdo do arquivo TXT |

**Resposta de sucesso:**
```json
{
  "sucesso": true,
  "lote": null,
  "documentos": 1,
  "status_cte": "OK"
}
```

**Resposta de erro:**
```json
{
  "sucesso": false,
  "erro": "Descrição do erro",
  "passo": "Passo 21 — Preencher dados dos fretes"
}
```

| `status_cte` | Significado |
|---|---|
| `"OK"` | CT-es autorizados com sucesso |
| `"INCONSISTENTE (N frete(s))"` | Fretes não corrigidos |
| `"REJEITADO (N frete(s))"` | CT-e rejeitado pela SEFAZ |
| `"PENDENTE (N frete(s))"` | Ainda processando |

---

### `GET /health`

Verifica se o browser está pronto.

```json
{
  "status": "ok",
  "browser": "conectado"
}
```

### `POST /buscar-cliente`

Busca um cliente na API do TMS por CNPJ.

**Body:**
```json
{
  "cnpj": "06042467000180",
  "nome": "BAGLEY"
}
```

---

## Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

| Variável | Descrição |
|---|---|
| `TMS_EMAIL` | E-mail de login no TMS |
| `TMS_PASSWORD` | Senha de login no TMS |
| `TMS_API_TOKEN` | Bearer token da API GraphQL do TMS |
| `TMS_HOST` | Host do TMS (ex: `mandalog.eslcloud.com.br`) |
| `SESSION_FILE` | Caminho do arquivo de sessão (default: `./data/session.json`) |
| `PORT` | Porta do servidor (default: `8000`) |
| `HEADLESS` | `true` para produção, `false` para debug (default: `true`) |
| `SLOW_MO` | Delay entre ações em ms (default: `0`, usar `600` para debug) |

---

## Deploy (EasyPanel)

1. Conectar o repositório `n4liice/emissao-cte-arcor` (branch `master`)
2. Configurar as variáveis de ambiente acima
3. O `Dockerfile` instala o Playwright e o Chromium automaticamente

---

## Execução local

```bash
# Instalar dependências
pip install -r requirements.txt
playwright install chromium

# Configurar variáveis
cp .env.example .env
# editar .env com as credenciais

# Rodar em modo debug (browser visível)
HEADLESS=false SLOW_MO=600 python rpa.py
```

---

## Estrutura do projeto

```
├── rpa.py          # Servidor FastAPI + lifespan do browser
├── browser.py      # Automação Playwright (fluxo completo)
├── session.py      # Gestão de login e sessão persistida
├── tms_api.py      # Integração API GraphQL do TMS
├── Dockerfile      # Build para produção
├── requirements.txt
└── .env.example
```
