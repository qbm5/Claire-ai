from pydantic import BaseModel
from typing import Any, Optional
from models.enums import ToolType, EndpointMethod, PropertyType


class Property(BaseModel):
    name: str = ""
    value: Any = ""
    description: str = ""
    type: PropertyType = PropertyType.TEXT
    is_required: bool = False
    locked: bool = False
    index: int = 0
    is_default: bool = False
    data: Any = None


class EnvVariable(BaseModel):
    name: str = ""
    description: str = ""
    type: PropertyType = PropertyType.TEXT  # TEXT or PASSWORD


class AgentFunction(BaseModel):
    uid: str = ""
    name: str = ""
    description: str = ""
    is_enabled: bool = True
    is_deleted: bool = False
    function_string: str = ""


class McpServer(BaseModel):
    uid: str = ""
    name: str = ""
    transport: int = 0  # 0=stdio, 1=http
    command: str = ""       # stdio: executable
    args: list[str] = []   # stdio: arguments
    url: str = ""           # http/sse: server URL
    is_enabled: bool = True
    allowed_tools: list[str] = []  # empty = allow all
    discovered_tools: list[dict] = []  # [{name, description}] from last test


class AiTool(BaseModel):
    id: str = ""
    name: str = ""
    type: ToolType = ToolType.LLM
    tag: str = ""
    sort_index: int = 0
    is_enabled: bool = True
    description: str = ""
    prompt: str = ""
    system_prompt: str = ""
    model: str = ""
    chatbot_id: str = ""
    endpoint_url: str = ""
    endpoint_method: EndpointMethod = EndpointMethod.GET
    endpoint_headers: str = ""
    endpoint_body: str = ""
    endpoint_query: list = []
    endpoint_timeout: int = 60
    agent_functions: list[AgentFunction] = []
    pipeline_id: str = ""
    pip_dependencies: list[str] = []
    env_variables: list[EnvVariable] = []
    mcp_servers: list[McpServer] = []
    # Claude Code Agent fields
    claude_code_allowed_tools: list[str] = []
    claude_code_permission_mode: str = "default"
    claude_code_working_dir: str = ""
    claude_code_bare: bool = True
    claude_code_mcp_config: str = ""
    claude_code_max_turns: int = 0
    claude_code_timeout: int = 600
    claude_code_json_schema: str = ""
    claude_code_system_prompt_mode: str = "append"
    response_structure: list = []
    request_inputs: list[Property] = []
    image_url: str = ""
    created_at: str = ""
    updated_at: str = ""
