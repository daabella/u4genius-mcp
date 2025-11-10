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
import os, httpx
from typing import Any, Dict, Optional
from uuid import uuid4
from mcp.server.fastmcp import FastMCP  # servidor MCP

APP_API_BASE = os.getenv("U4GENIUS_API_BASE", "https://u4genius-api.onrender.com").rstrip("/")
TIMEOUT = float(os.getenv("U4GENIUS_TIMEOUT", "25"))

# ---- Estado en memoria del MCP (demo) ----
MCP_SESSION: Dict[str, Any] = {"session_id": None, "company": None, "available_queries": []}

async def _post_json(path: str, payload: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    url = f"{APP_API_BASE}/{path.lstrip('/')}"
    headers = {"X-Session-Id": session_id} if session_id else {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json=payload, headers=headers); r.raise_for_status(); return r.json()

async def _get_json(path: str, params: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    url = f"{APP_API_BASE}/{path.lstrip('/')}"
    headers = {"X-Session-Id": session_id} if session_id else {}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, params=params, headers=headers); r.raise_for_status(); return r.json()

mcp = FastMCP("U4Genius MCP", streamable_http_path="/")

@mcp.tool()
async def inicializar_sesion(company: str) -> Dict[str, Any]:
    """Activa sesión en el BFF y guarda la lista de consultas en el MCP."""
    if not company:
        return {"error": "company requerido"}
    data = await _post_json("/inicializar_sesion", {"company": company})
    MCP_SESSION["session_id"] = data.get("session_id") or str(uuid4())
    MCP_SESSION["company"] = data.get("company")
    MCP_SESSION["available_queries"] = data.get("available_queries", [])

    consultas = MCP_SESSION["available_queries"]
    if consultas:
        bullets = "\n".join([f"• {c.get('reportname') or c.get('objectid')} (objectid: {c.get('objectid')})" for c in consultas])
        msg = f"✅ Compañía cambiada a {company}.\nEstas son las consultas disponibles:\n{bullets}"
    else:
        msg = f"✅ Compañía cambiada a {company}. No se encontraron consultas."
    return {"message": msg, **{k: MCP_SESSION[k] for k in ("company","session_id","available_queries")}}

@mcp.tool()
async def listar_reportes() -> Dict[str, Any]:
    """Devuelve la lista guardada en la sesión del MCP."""
    if not MCP_SESSION.get("company"):
        return {"warning": "No hay compañía activa. Llama a inicializar_sesion(company='EN')."}
    return {k: MCP_SESSION[k] for k in ("company","session_id","available_queries")}

@mcp.tool()
async def obtener_columnas(objectid: str, company: Optional[str] = None) -> Dict[str, Any]:
    company = company or MCP_SESSION.get("company")
    if not company:
        return {"error": "company requerido (o inicializa sesión primero)"}
    sid = MCP_SESSION.get("session_id")
    return await _get_json("/columnas", {"objectid": objectid, "company": company}, session_id=sid)

@mcp.tool()
async def consultar_reporte(pregunta: str) -> Dict[str, Any]:
    sid = MCP_SESSION.get("session_id")
    return await _post_json("/consultar_reporte", {"pregunta": pregunta}, session_id=sid)

app = mcp.streamable_http_app()
