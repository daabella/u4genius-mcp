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

from __future__ import annotations

import os
import json
import httpx
from typing import Any, Dict, List, Optional
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# SDK MCP (HTTP/SSE sobre FastAPI)
from mcp.server.fastapi import FastAPIMCPServer
from mcp.types import (
    Tool,
    ListToolsResult,
    CallToolRequest,
    CallToolResult,
    Prompt,
    ListPromptsResult,
)

# ===================== Config =====================
APP_API_BASE = os.getenv("U4GENIUS_API_BASE", "https://u4genius-api.onrender.com")
TIMEOUT = float(os.getenv("U4GENIUS_TIMEOUT", "25"))

# ===================== App / MCP =====================
app = FastAPI(title="U4Genius MCP Gateway")
mcp = FastAPIMCPServer()

# Health simple para Render/monitoring
@app.get("/health")
async def health():
    return {"ok": True, "service": "u4genius-mcp"}

# ========== Helpers HTTP ==========
async def _post_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APP_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()

async def _get_json(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{APP_API_BASE.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r.json()

# ===================== Prompts MCP =====================
@mcp.list_prompts()
async def list_prompts() -> ListPromptsResult:
    return ListPromptsResult(
        prompts=[
            Prompt(
                name="conectar_compania",
                description="Crea el mensaje adecuado para activar una compañía en sesión.",
                arguments=[{"name": "company", "description": "Id de compañía (ej. EN)", "required": True}],
            )
        ]
    )

# ===================== Tools MCP =====================
@mcp.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(
        tools=[
            Tool(
                name="inicializar_sesion",
                description="Activa la sesión para una compañía y devuelve los browsers/reportes disponibles.",
                inputSchema={
                    "type": "object",
                    "properties": {"company": {"type": "string"}},
                    "required": ["company"],
                },
            ),
            Tool(
                name="listar_reportes",
                description="Devuelve lista de reportes disponibles de la sesión (atalho a inicializar_sesion si se pasa company).",
                inputSchema={
                    "type": "object",
                    "properties": {"company": {"type": "string"}},
                },
            ),
            Tool(
                name="obtener_columnas",
                description="Devuelve metadatos/columnas de un browser (Unit4 object).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "objectid": {"type": "string"},
                        "company": {"type": "string"},
                    },
                    "required": ["objectid", "company"],
                },
            ),
            Tool(
                name="consultar_reporte",
                description="Ejecuta un reporte/browser para una compañía y periodo (contrato mínimo).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pregunta": {"type": "string", "description": "Texto natural con el nombre del reporte o consulta."}
                    },
                    "required": ["pregunta"],
                },
            ),
        ]
    )

@mcp.call_tool()
async def call_tool(req: CallToolRequest) -> CallToolResult:
    """Dispatcher de herramientas MCP → app.py (API propia)."""
    name = req.name
    args = req.arguments or {}

    try:
        if name == "inicializar_sesion":
            data = await _post_json("/inicializar_sesion", {"company": args.get("company", "").strip()})
            # El API devuelve browsers; el asistente podrá presentarlos al usuario
            return CallToolResult(content=[{"type": "json", "json": data}])

        if name == "listar_reportes":
            company = (args.get("company") or "").strip()
            if company:
                data = await _post_json("/inicializar_sesion", {"company": company})
            else:
                # Si no se pasa company, no hay estado aquí; mantenemos la llamada idéntica para simplicidad
                data = {"warning": "Sin parámetro company. Llama primero a inicializar_sesion."}
            return CallToolResult(content=[{"type": "json", "json": data}])

        if name == "obtener_columnas":
            data = await _get_json("/columnas", {"objectid": args.get("objectid"), "company": args.get("company")})
            return CallToolResult(content=[{"type": "json", "json": data}])

        if name == "consultar_reporte":
            # Para compatibilidad temprana reutilizamos el contrato de app.py que acepta {pregunta}
            data = await _post_json("/consultar_reporte", {"pregunta": args.get("pregunta", "")})
            return CallToolResult(content=[{"type": "json", "json": data}])

        return CallToolResult(isError=True, content=[{"type": "text", "text": f"Tool no soportada: {name}"}])

    except httpx.HTTPStatusError as e:
        return CallToolResult(
            isError=True,
            content=[{"type": "text", "text": f"HTTP {e.response.status_code}: {e.response.text}"}],
        )
    except Exception as e:  # noqa: BLE001
        return CallToolResult(isError=True, content=[{"type": "text", "text": f"Error: {e}"}])

# Montar el transporte MCP en la app FastAPI raíz (en '/')
app.mount("/", mcp.app)
