"""
main.py - Worker RPA Mandalog
"""

import asyncio
import base64
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from logging import FileHandler, StreamHandler

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
from pydantic import BaseModel

from browser import importar_xml
from tms_api import buscar_cliente_por_cnpj, buscar_cliente_por_nome

# Fix para Windows - deve ser antes de qualquer uso relevante do asyncio/playwright
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

load_dotenv()

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
LOG_FILE = os.path.join(LOG_DIR, "rpa.log")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        StreamHandler(sys.stdout),
        FileHandler(LOG_FILE, encoding="utf-8"),
    ],
    force=True,
)
logger = logging.getLogger(__name__)

logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.error").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.INFO)

_playwright = None
_browser = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _playwright, _browser
    logger.info("Iniciando automacao...")
    logger.info("Logs em arquivo: %s", LOG_FILE)
    headless = os.environ.get("HEADLESS", "true").lower() == "true"
    slow_mo  = int(os.environ.get("SLOW_MO", "0"))
    logger.info("Browser: headless=%s slow_mo=%d", headless, slow_mo)
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(
        headless=headless,
        slow_mo=slow_mo,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    )
    logger.info("Browser Chromium pronto.")
    yield
    logger.info("Encerrando automacao...")
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()


app = FastAPI(
    title="RPA Worker - Mandalog",
    description="Automacao para emissao de CT-e",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class BuscarClienteRequest(BaseModel):
    cnpj: str
    nome: str | None = None


class XmlFilePayload(BaseModel):
    name: str
    content_base64: str


class TxtItem(BaseModel):
    filename: str
    numero_oc: str
    xml: str
    tipo_operacao: str = "TRANSFERENCIA"  # "TRANSFERENCIA" ou "COLETA DE PBR"
    numero_pbr: str | None = None


class ImportarRequest(BaseModel):
    customer_id: str
    corporation_id: str = "MANDALOG OPERACOES E LOGISTICAS"
    customer_name: str | None = None
    # formato N8N: lista de itens {filename, numero_oc, xml}
    items: list[TxtItem] | None = None
    # formatos legados
    xml: str | None = None
    txt: str | None = None
    oc: str | None = None
    xml_files: list[XmlFilePayload] | None = None
    xml_contents: list[str] | None = None




@app.get("/health")
async def health():
    browser_ok = _browser is not None and _browser.is_connected()
    logger.info("GET /health -> browser_ok=%s", browser_ok)
    return {
        "status": "ok" if browser_ok else "degraded",
        "browser": "conectado" if browser_ok else "desconectado",
    }


@app.post("/buscar-cliente")
async def buscar_cliente(req: BuscarClienteRequest):
    logger.info("POST /buscar-cliente cnpj=%s nome=%s", req.cnpj, req.nome)
    try:
        cliente = await buscar_cliente_por_cnpj(req.cnpj)
        if cliente:
            logger.info(
                "Cliente encontrado para cnpj=%s id=%s nome=%s",
                req.cnpj,
                cliente.get("id"),
                cliente.get("nome"),
            )
            return JSONResponse(status_code=200, content={"encontrado": True, "cliente": cliente})

        sugestoes = []
        if req.nome:
            sugestoes = await buscar_cliente_por_nome(req.nome, limite=5)
        logger.info("Cliente nao encontrado para cnpj=%s; sugestoes=%d", req.cnpj, len(sugestoes))
        return JSONResponse(
            status_code=200,
            content={
                "encontrado": False,
                "sugestoes": sugestoes,
                "mensagem": f"CNPJ {req.cnpj} nao encontrado.",
            },
        )
    except RuntimeError as e:
        logger.warning("Erro de negocio em /buscar-cliente: %s", e)
        return JSONResponse(status_code=400, content={"erro": str(e)})
    except Exception as e:
        logger.exception("Erro inesperado em /buscar-cliente")
        return JSONResponse(status_code=500, content={"erro": str(e)})


@app.post("/importar")
async def importar(req: ImportarRequest):
    if _browser is None or not _browser.is_connected():
        logger.warning("Automacao indisponivel no momento da importacao.")
        return JSONResponse(status_code=503, content={"erro": "Automacao nao disponivel."})

    # Resolve xml_files e OC a partir do formato recebido
    if req.items:
        # formato N8N: [{filename, numero_oc, xml, tipo_operacao, numero_pbr}, ...]
        ocs = [item.numero_oc for item in req.items if item.numero_oc]
        oc = _normalizar_oc(",".join(ocs))
        xml_files = [
            {
                "name": item.filename,
                "content_base64": base64.b64encode(item.xml.encode("utf-8")).decode(),
            }
            for item in req.items
        ]
        customer_name = req.customer_name or req.customer_id
        tipo_operacao = req.items[0].tipo_operacao
        numero_pbr = req.items[0].numero_pbr
    elif req.txt is not None:
        xmls = _split_xmls_from_txt(req.txt)
        xml_files = [
            {
                "name": _extrair_nome_nfe(x),
                "content_base64": base64.b64encode(x.encode("utf-8")).decode(),
            }
            for x in xmls
        ]
        customer_name = req.customer_name or (
            _extrair_nome_emitente(xmls[0]) if xmls else None
        ) or req.customer_id
        oc = _normalizar_oc(req.oc)
        tipo_operacao = "TRANSFERENCIA"
        numero_pbr = None
    elif req.xml is not None:
        xml_b64 = base64.b64encode(req.xml.encode("utf-8")).decode()
        xml_files = [{"name": _extrair_nome_nfe(req.xml), "content_base64": xml_b64}]
        customer_name = req.customer_name or _extrair_nome_emitente(req.xml) or req.customer_id
        oc = _normalizar_oc(req.oc)
        tipo_operacao = "TRANSFERENCIA"
        numero_pbr = None
    elif req.xml_files:
        xml_files = [item.model_dump() for item in req.xml_files]
        customer_name = req.customer_name or req.customer_id
        oc = _normalizar_oc(req.oc)
        tipo_operacao = "TRANSFERENCIA"
        numero_pbr = None
    elif req.xml_contents:
        xml_files = [
            {"name": f"documento_{i + 1}.xml", "content_base64": c}
            for i, c in enumerate(req.xml_contents)
        ]
        customer_name = req.customer_name or req.customer_id
        oc = _normalizar_oc(req.oc)
        tipo_operacao = "TRANSFERENCIA"
        numero_pbr = None
    else:
        return JSONResponse(status_code=400, content={"erro": "Nenhum XML fornecido."})
    logger.info(
        "POST /importar customer_id=%s customer_name=%s corporation=%s arquivos=%d oc=%s tipo=%s",
        req.customer_id,
        customer_name,
        req.corporation_id,
        len(xml_files),
        oc,
        tipo_operacao,
    )

    resultado = await importar_xml(
        browser=_browser,
        customer_id=req.customer_id,
        customer_name=customer_name,
        corporation_name=req.corporation_id,
        xml_files=xml_files,
        oc=oc,
        tipo_operacao=tipo_operacao,
        numero_pbr=numero_pbr,
    )
    status = 200 if resultado.get("sucesso") else 422
    logger.info(
        "Resposta /importar status=%s sucesso=%s lote=%s erro=%s passo=%s",
        status,
        resultado.get("sucesso"),
        resultado.get("lote"),
        resultado.get("erro"),
        resultado.get("passo"),
    )
    return JSONResponse(status_code=status, content=resultado)


_NFE_NS = "http://www.portalfiscal.inf.br/nfe"


def _split_xmls_from_txt(txt: str) -> list[str]:
    """Extrai um ou dois documentos XML de um conteudo TXT."""
    txt = txt.strip()

    # Caso 1: múltiplas declarações <?xml → cada uma inicia um documento
    positions = [m.start() for m in re.finditer(r"<\?xml\b", txt, re.IGNORECASE)]
    if len(positions) >= 2:
        parts = []
        for i, start in enumerate(positions):
            end = positions[i + 1] if i + 1 < len(positions) else len(txt)
            part = txt[start:end].strip()
            if part:
                parts.append(part)
        return parts

    # Caso 2: sem declaração ou declaração única → tenta parse direto
    try:
        ET.fromstring(txt)
        return [txt]
    except ET.ParseError as e:
        # "junk after document element" → dois elementos raiz colados sem declaração
        if "junk after document element" in str(e):
            try:
                root = ET.fromstring(f"<_r_>{txt}</_r_>")
                return [ET.tostring(child, encoding="unicode") for child in root]
            except Exception:
                pass

    return [txt]


def _extrair_nome_emitente(xml_str: str) -> str | None:
    try:
        root = ET.fromstring(xml_str)
        el = root.find(f".//{{{_NFE_NS}}}emit/{{{_NFE_NS}}}xNome")
        if el is not None and el.text:
            return el.text.strip()
    except Exception:
        pass
    return None


def _extrair_nome_nfe(xml_str: str) -> str:
    try:
        root = ET.fromstring(xml_str)
        el = root.find(f".//{{{_NFE_NS}}}nNF")
        if el is not None and el.text:
            return f"nfe_{el.text.strip()}.xml"
    except Exception:
        pass
    return "documento.xml"


def _normalizar_oc(oc: str | None) -> str | None:
    if not oc:
        return None
    oc = oc.strip()
    if not oc:
        return None

    # Separa caso venha múltiplas OCs delimitadas (vírgula, ponto-e-vírgula, nova linha)
    partes = [p.strip() for p in re.split(r"[,;\n\r]+", oc) if p.strip()]
    if len(partes) <= 1:
        return oc

    # Deduplicar mantendo ordem
    unicos = list(dict.fromkeys(partes))
    # Mesma OC repetida → retorna uma só; OCs distintas → concatena sem separador
    # Ex: ["5139621", "5139623"] → "51396215139623"
    return unicos[0] if len(unicos) == 1 else "".join(unicos)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "rpa:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        loop="asyncio",
        access_log=True,
    )
