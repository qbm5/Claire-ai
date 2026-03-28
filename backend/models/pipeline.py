from pydantic import BaseModel, computed_field
from typing import Optional
from models.enums import PipelineStatusType, ToolType
from models.tool import AiTool, Property
from config import get_model_pricing, MILLION


class NodeEdge(BaseModel):
    id: str = ""
    source: str = ""
    target: str = ""
    source_handle: str = ""
    target_handle: str = ""


class AICost(BaseModel):
    detail: str = ""
    model: str = ""
    input_token_count: int = 0
    output_token_count: int = 0

    @computed_field
    @property
    def input_cost(self) -> float:
        p = get_model_pricing(self.model)
        return (p["input_cost"] / MILLION) * self.input_token_count

    @computed_field
    @property
    def output_cost(self) -> float:
        p = get_model_pricing(self.model)
        return (p["output_cost"] / MILLION) * self.output_token_count

    @computed_field
    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost


class AiPipelineStep(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    next_steps: list[str] = []
    next_steps_true: list[str] = []
    next_steps_false: list[str] = []
    is_start: bool = False
    tool_id: str = ""
    tool: Optional[AiTool] = None
    status: PipelineStatusType = PipelineStatusType.Pending
    inputs: list[Property] = []
    outputs: list[Property] = []
    call_cost: list[AICost] = []
    status_text: str = ""
    pre_process: str = ""
    post_process: str = ""
    disabled: bool = False
    tool_outputs: list[str] = []
    pause_after: bool = False
    retry_enabled: bool = False
    max_retries: int = 1
    validation_enabled: bool = False
    validation_model: str = ""
    memory_id: str = ""
    pos_x: float = 0
    pos_y: float = 0


class AiPipeline(BaseModel):
    id: str = ""
    name: str = ""
    description: str = ""
    tag: str = ""
    image_url: str = ""
    steps: list[AiPipelineStep] = []
    inputs: list[Property] = []
    edges: list[NodeEdge] = []
    guidance: str = ""
    validation_model: str = ""
    created_at: str = ""
    updated_at: str = ""


class AiPipelineRun(BaseModel):
    id: str = ""
    pipeline_id: str = ""
    pipeline_snapshot: Optional[AiPipeline] = None
    steps: list[AiPipelineStep] = []
    inputs: list[Property] = []
    outputs: list[Property] = []
    status: PipelineStatusType = PipelineStatusType.Pending
    current_step: int = 0
    guidance: str = ""
    created_at: str = ""
    completed_at: str = ""

    @computed_field
    @property
    def total_cost(self) -> float:
        return sum(c.total_cost for s in self.steps for c in s.call_cost)

    @computed_field
    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_token_count for s in self.steps for c in s.call_cost)

    @computed_field
    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_token_count for s in self.steps for c in s.call_cost)
