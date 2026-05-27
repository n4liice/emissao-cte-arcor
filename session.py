"""
session.py - Gestao de sessao e login no TMS.
Reutiliza sessao salva em disco e mantem a janela aberta entre requisicoes.
"""

import logging
import os

logger = logging.getLogger(__name__)

SESSION_FILE = os.environ.get("SESSION_FILE", "./data/session.json")
BASE_URL = "https://mandalog.eslcloud.com.br"
LOGIN_URL = f"{BASE_URL}/users/sign_in"
BATCHES_URL = f"{BASE_URL}/edi/import/batches"

_context = None
_page = None


async def get_authenticated_page(browser):
    """
    Retorna (page, context) autenticada.
    1. Reutiliza a janela atual se ela ainda estiver aberta e logada.
    2. Tenta sessao salva em disco.
    3. Se expirada, faz login e salva nova sessao.
    """
    global _context, _page

    if _context and _page:
        try:
            if not _page.is_closed():
                await _page.goto(BATCHES_URL, wait_until="networkidle", timeout=20000)
                if "/users/sign_in" not in _page.url:
                    logger.info("Reutilizando janela existente do Chromium.")
                    return _page, _context
            await _fechar_contexto_ativo()
        except Exception as e:
            logger.warning("Falha ao reutilizar janela existente: %s", e)
            await _fechar_contexto_ativo()

    if os.path.exists(SESSION_FILE):
        logger.info("Sessao encontrada - verificando validade...")
        try:
            context = await browser.new_context(storage_state=SESSION_FILE)
            page = await context.new_page()
            await page.goto(BATCHES_URL, wait_until="networkidle", timeout=20000)
            if "/users/sign_in" not in page.url:
                logger.info("Sessao valida reutilizada.")
                _context = context
                _page = page
                return page, context
            logger.warning("Sessao expirada - refazendo login...")
            await context.close()
        except Exception as e:
            logger.warning("Erro ao carregar sessao: %s", e)
            try:
                await context.close()
            except Exception:
                pass

    return await _fazer_login(browser)


async def _fazer_login(browser):
    global _context, _page

    email = os.environ.get("TMS_EMAIL")
    senha = os.environ.get("TMS_PASSWORD")

    if not email or not senha:
        raise RuntimeError("TMS_EMAIL e TMS_PASSWORD nao configurados no .env")

    logger.info("Fazendo login com: %s", email)
    context = await browser.new_context()
    page = await context.new_page()

    try:
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=20000)
        await page.fill("#user_email", email)
        await page.fill("#user_password", senha)
        await page.click("input[type=submit]")
        await page.wait_for_function(
            "() => !window.location.href.includes('/users/sign_in')",
            timeout=15000,
        )
        logger.info("Login realizado. URL: %s", page.url)
    except Exception as e:
        await context.close()
        raise RuntimeError(f"Falha no login: {e}") from e

    try:
        os.makedirs(os.path.dirname(os.path.abspath(SESSION_FILE)), exist_ok=True)
        await context.storage_state(path=SESSION_FILE)
        logger.info("Sessao salva em: %s", SESSION_FILE)
    except Exception as e:
        logger.warning("Nao foi possivel salvar sessao: %s", e)

    _context = context
    _page = page
    return page, context


async def limpar_sessao():
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
        logger.info("Sessao removida.")
    await _fechar_contexto_ativo()


async def _fechar_contexto_ativo():
    global _context, _page

    context = _context
    _context = None
    _page = None

    if context:
        try:
            await context.close()
        except Exception:
            pass
