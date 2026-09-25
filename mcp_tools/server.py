import asyncio
import inspect

from fastapi import HTTPException
from mcp.server.mcpserver import Context, MCPServer

from db.connection import db_manager
from server.auth_api import AuthApi
from server.registry import TOOLS, Tool
from server.sandbox_api import CreateSandboxRequest, SandboxApi, to_response


def build_mcp(auth: AuthApi, sandboxes: SandboxApi) -> MCPServer:
    mcp = MCPServer("zoo")

    def user_of(ctx: Context):
        header = (ctx.headers or {}).get("authorization", "")
        with db_manager.session() as db:
            user = auth.user_from_token(header.removeprefix("Bearer ").strip(), db)
        if user is None:
            raise ValueError("unauthorized: pass Authorization: Bearer <zoo api key>")
        return user

    def wrap(tool: Tool):
        async def handler(ctx: Context, sandbox_id: str, **kwargs):
            try:
                return await sandboxes.run_tool(user_of(ctx), sandbox_id, tool.name, kwargs, "mcp")
            except HTTPException as e:
                raise ValueError(e.detail)

        params = [
            inspect.Parameter("ctx", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Context),
            inspect.Parameter("sandbox_id", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=str),
            *[p.replace(kind=inspect.Parameter.POSITIONAL_OR_KEYWORD) for p in tool.params],
        ]
        handler.__signature__ = inspect.Signature(params)
        handler.__annotations__ = {p.name: p.annotation for p in params}
        handler.__name__ = tool.name
        return handler

    for tool in TOOLS.values():
        mcp.add_tool(
            wrap(tool),
            name=tool.name,
            description=f"{tool.category}: {tool.name.replace('_', ' ')} (requires {tool.permission}.{tool.action})",
        )

    @mcp.tool()
    def list_sandboxes(ctx: Context) -> list[dict]:
        user = user_of(ctx)
        with db_manager.session() as db:
            return [to_response(s).model_dump() for s in db.list_sandboxes_by_user(created_by=user.id)]

    @mcp.tool()
    async def create_sandbox(ctx: Context, name: str | None = None) -> dict:
        user = user_of(ctx)
        with db_manager.session() as db:
            sandbox = sandboxes.create(CreateSandboxRequest(name=name), user, db)
        asyncio.get_running_loop().run_in_executor(None, sandboxes.boot, sandbox.id)
        return to_response(sandbox).model_dump()

    @mcp.tool()
    def get_sandbox(ctx: Context, sandbox_id: str) -> dict:
        user = user_of(ctx)
        with db_manager.session() as db:
            try:
                return to_response(sandboxes.owned(sandbox_id, user, db)).model_dump()
            except HTTPException as e:
                raise ValueError(e.detail)

    return mcp
