"""
tms_api.py — Integração com a API GraphQL do TMS.
Utiliza Bearer Token para autenticação.
"""

import os
import logging
import httpx

logger = logging.getLogger(__name__)

BASE_URL  = lambda: f"https://{os.environ.get('TMS_HOST', '')}/graphql"
API_TOKEN = lambda: os.environ.get("TMS_API_TOKEN", "")

QUERY_BUSCAR_EMPRESA = """
query buscarEmpresa($params: CompanyInput!, $first: Int) {
  company(params: $params, first: $first) {
    edges {
      node {
        active
        baseCnpj
        cfopCode
        cnaeCode
        cnpj
        code
        comments
        email
        id
        inscricaoEstadual
        inscricaoMunicipal
        mobileNumber
        name
        nickname
        phoneNumber
        pisCode
        rntrc
        rntrcExpirationDate
        suframaCode
        type
        costCenters {
          name
          id
        }
        mainAddress {
          line1
          line2
          number
          postalCode
          neighborhood
          lat
          lng
          isDefault
          city {
            name
            state { code }
          }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _headers() -> dict:
    token = API_TOKEN()
    if not token:
        raise RuntimeError(
            "Variável TMS_API_TOKEN não configurada. "
            "Gere o token em: Cadastros > Usuários > Aba API > Gerar token"
        )
    auth = token if token.startswith("Bearer ") else f"Bearer {token}"
    return {
        "Content-Type": "application/json",
        "Authorization": auth,
    }


async def buscar_cliente_por_cnpj(cnpj: str) -> dict | None:
    """
    Busca pessoa jurídica pelo CNPJ.
    Retorna dict com os dados ou None se não encontrado.
    """
    cnpj_limpo = "".join(filter(str.isdigit, cnpj))
    logger.info("Buscando CNPJ %s...", cnpj_limpo)

    payload = {
        "query": QUERY_BUSCAR_EMPRESA,
        "variables": {
            "params": {"cnpj": cnpj_limpo, "enabled": True},
            "first": 1,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(BASE_URL(), json=payload, headers=_headers())

    if response.status_code == 401:
        raise RuntimeError("Token de API inválido ou expirado.")
    if response.status_code == 429:
        raise RuntimeError("Muitas requisições. Aguarde 2 segundos e tente novamente.")
    if response.status_code != 200:
        raise RuntimeError(f"Erro na API: HTTP {response.status_code}")

    data = response.json()
    if "errors" in data:
        erros = "; ".join(e.get("message", str(e)) for e in data["errors"])
        raise RuntimeError(f"Erro na consulta: {erros}")

    edges = data.get("data", {}).get("company", {}).get("edges", [])
    if not edges:
        logger.warning("CNPJ %s não encontrado.", cnpj_limpo)
        return None

    return _montar_cliente(edges[0]["node"])


async def buscar_cliente_por_nome(nome: str, limite: int = 5) -> list[dict]:
    """Busca por nome — fallback quando CNPJ não é encontrado."""
    logger.info("Buscando por nome '%s'...", nome)

    payload = {
        "query": QUERY_BUSCAR_EMPRESA,
        "variables": {
            "params": {"name": nome.upper(), "enabled": True},
            "first": limite,
        },
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(BASE_URL(), json=payload, headers=_headers())

    if response.status_code != 200:
        raise RuntimeError(f"Erro na API: HTTP {response.status_code}")

    data = response.json()
    if "errors" in data:
        erros = "; ".join(e.get("message", str(e)) for e in data["errors"])
        raise RuntimeError(f"Erro na consulta: {erros}")

    edges = data.get("data", {}).get("company", {}).get("edges", [])
    return [_montar_cliente(e["node"]) for e in edges]


def _montar_cliente(node: dict) -> dict:
    """Transforma o nó GraphQL num dict limpo para o front-end."""
    endereco = node.get("mainAddress") or {}
    cidade   = endereco.get("city") or {}
    estado   = cidade.get("state") or {}
    return {
        "id":            node.get("id"),
        "ativo":         node.get("active", True),
        "codigo":        node.get("code", ""),
        "nome":          node.get("name", ""),
        "nomeFantasia":  node.get("nickname", ""),
        "cnpj":          node.get("cnpj", ""),
        "cnpjBase":      node.get("baseCnpj", ""),
        "email":         node.get("email", ""),
        "telefone":      node.get("phoneNumber", ""),
        "celular":       node.get("mobileNumber", ""),
        "ie":            node.get("inscricaoEstadual", ""),
        "im":            node.get("inscricaoMunicipal", ""),
        "cfop":          node.get("cfopCode", ""),
        "cnae":          node.get("cnaeCode", ""),
        "pis":           node.get("pisCode", ""),
        "rntrc":         node.get("rntrc", ""),
        "rntrcValidade": node.get("rntrcExpirationDate", ""),
        "suframa":       node.get("suframaCode", ""),
        "tipo":          node.get("type", ""),
        "observacoes":   node.get("comments", ""),
        "centrosCusto":  node.get("costCenters") or [],
        "cidade":        cidade.get("name", ""),
        "uf":            estado.get("code", ""),
        "logradouro":    endereco.get("line1", ""),
        "complemento":   endereco.get("line2", ""),
        "numero":        endereco.get("number", ""),
        "bairro":        endereco.get("neighborhood", ""),
        "cep":           endereco.get("postalCode", ""),
    }
