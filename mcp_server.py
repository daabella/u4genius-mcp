"""
MCP servidor orquestador para U4Genius (v1)

Arquitectura: ChatGPT (Connector MCP) → ESTE servidor MCP → API propia (app.py) → Unit4 ERP

Razonamiento: mantenemos app.py como BFF (backend-for-frontend) que concentra auth,
normalización y cambios del ERP; el MCP expone herramientas/propmpts estándar del
protocolo y orquesta llamadas conversacionales. Así evitamos acoplar el conector a
APIs del ERP y podemos evolucionar la lógica sin romper el handshake MCP.

Requisitos (requirements.txt):
  fastapi
  uvicorn
  httpx
  mcp  # SDK Python oficial del Model Context Protocol

Ejecución local:
  uvicorn mcp_server:app --host 0.0.0.0 --port 8000
La URL MCP a poner en ChatGPT Connector será, por ejemplo, https://<tu-host>/ (o /mcp si cambias el root_path).
"""

# mcp_server.py
from __future__ import annotations
import os
import httpx
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP  # Servidor MCP (Streamable HTTP)

# ----------------- Config -----------------
APP_API_BASE = os.getenv("U4GENIUS_API_BASE", "https://u4genius-api.onrender.com").rstrip("/")
TIMEOUT = float(os.getenv("U4GENIUS_TIMEOUT", "25"))

# ----------------- HTTP helpers -----------------
async def _post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APP_API_BASE}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

async def _get_json(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APP_API_BASE}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

# ----------------- MCP server -----------------
# IMPORTANTE: exponer en la raíz "/" para que reciba lifespan.
mcp = FastMCP("U4Genius MCP", streamable_http_path="/")

# Prompt de ayuda (opcional)
@mcp.prompt()
def conectar_compania(company: str):
    """Devuelve una frase modelo para iniciar sesión con una compañía."""
    return f"Conectar a compañía {company}"

# Tools MCP
@mcp.tool()
async def inicializar_sesion(company: str) -> Dict[str, Any]:
    """Activa la sesión para una compañía y devuelve browsers/reportes disponibles."""
    if not company:
        return {"error": "company requerido"}
    return await _post_json("/inicializar_sesion", {"company": company})

@mcp.tool()
async def listar_reportes(company: str | None = None) -> Dict[str, Any]:
    """Alias: si llega company, llama a inicializar_sesion; si no, avisa."""
    if company:
        return await _post_json("/inicializar_sesion", {"company": company})
    return {"warning": "Sin parámetro company. Llama primero a inicializar_sesion."}

@mcp.tool()
async def obtener_columnas(objectid: str, company: str) -> Dict[str, Any]:
    """Devuelve metadatos/columnas de un browser (Unit4 object)."""
    return await _get_json("/columnas", {"objectid": objectid, "company": company})

@mcp.tool()
async def consultar_reporte(pregunta: str) -> Dict[str, Any]:
    """Ejecuta una consulta usando el contrato actual del BFF."""
    return await _post_json("/consultar_reporte", {"pregunta": pregunta})

# ----------------- ASGI app raíz -----------------
# No envolvemos con Starlette; así el MCP recibe lifespan.
app = mcp.streamable_http_app()
