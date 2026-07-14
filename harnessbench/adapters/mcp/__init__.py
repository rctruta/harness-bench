"""Generic MCP Target Adapter.

Bridges an arbitrary MCP server (via stdio) to the `TargetAdapter` protocol.
This allows harness-bench to execute the Monolith Baseline against any MCP server.
"""
import asyncio
import json
import threading
from typing import Dict, List, Optional, Callable

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from mcp.client.session import ClientSession

from harnessbench.adapter import TargetAdapter, SpecialistRole, TerminalPolicy


class McpAdapter(TargetAdapter):
    """Generic MCP adapter using a background asyncio event loop."""

    def __init__(self, command: Optional[List[str]] = None, url: Optional[str] = None):
        if bool(command) == bool(url):
            raise ValueError("McpAdapter needs exactly one of command (stdio) or url (http)")
        self._command = command
        self._url = url
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        self._tools_cache: Optional[List[dict]] = None
        self._ready_event = threading.Event()
        self._error = None
        
        # Start the MCP connection asynchronously
        asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        self._ready_event.wait(timeout=15.0)
        
        if self._error:
            raise RuntimeError(f"Failed to connect to MCP server: {self._error}")
            
    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self):
        try:
            # We must hold the context managers open indefinitely.
            # To do this safely in a background thread, we enter them manually.
            if self._url:
                self._transport_cm = streamablehttp_client(self._url)
                self._read_stream, self._write_stream, _ = await self._transport_cm.__aenter__()
            else:
                server_params = StdioServerParameters(
                    command=self._command[0],
                    args=self._command[1:],
                )
                self._transport_cm = stdio_client(server_params)
                self._read_stream, self._write_stream = await self._transport_cm.__aenter__()
            
            self._session_cm = ClientSession(self._read_stream, self._write_stream)
            self._session = await self._session_cm.__aenter__()
            
            await self._session.initialize()
            self._ready_event.set()
        except Exception as e:
            self._error = e
            self._ready_event.set()

    @property
    def name(self) -> str:
        if self._url:
            return f"mcp:http:{self._url}"
        return f"mcp:stdio:{' '.join(self._command)}"

    def healthcheck(self) -> None:
        """Verify the MCP connection is alive."""
        if self._error or not getattr(self, '_session', None):
            raise RuntimeError("MCP server connection is dead.")

    def tools(self, neutral_descriptions: bool = False) -> List[dict]:
        if self._tools_cache is not None:
            return self._tools_cache
            
        async def _fetch():
            res = await self._session.list_tools()
            return res.tools
            
        future = asyncio.run_coroutine_threadsafe(_fetch(), self._loop)
        mcp_tools = future.result(timeout=10.0)
        
        litellm_tools = []
        for t in mcp_tools:
            litellm_tools.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                }
            })
        self._tools_cache = litellm_tools
        return litellm_tools

    def execute_tool(self, name: str, args: dict) -> str:
        async def _exec():
            res = await self._session.call_tool(name, arguments=args)
            return res.content
            
        future = asyncio.run_coroutine_threadsafe(_exec(), self._loop)
        content_items = future.result(timeout=60.0)
        
        # content is a list of TextContent/ImageContent etc.
        # We naively serialize it to string for the LLM.
        texts = []
        for item in content_items:
            if item.type == "text":
                texts.append(item.text)
            elif item.type == "resource":
                # EmbeddedResource: surface the actual payload, not a placeholder.
                res = getattr(item, "resource", None)
                text = getattr(res, "text", None)
                texts.append(text if text is not None else f"[non-text resource: {getattr(res, 'uri', '?')}]")
            else:
                texts.append(f"[{item.type} content]")
        return "\n".join(texts)

    def roles(self) -> Dict[str, SpecialistRole]:
        # Returns {} so the Orchestrator falls back to MonolithDriver
        return {}

    def terminal_policy(self) -> Optional[TerminalPolicy]:
        return None

    def grader(self) -> Optional[Callable[[dict], dict]]:
        return None

    def markers(self) -> Dict[str, Callable]:
        return {}
