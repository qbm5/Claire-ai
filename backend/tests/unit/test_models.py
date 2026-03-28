"""Tests for backend Pydantic models."""

from unittest.mock import patch
from models.enums import ToolType, PropertyType, PipelineStatusType, EndpointMethod
from models.tool import AiTool, Property, AgentFunction, McpServer, EnvVariable
from models.chatbot import ChatBot, ChatMessage, ChatHistory
from models.pipeline import AiPipeline, AiPipelineStep, AiPipelineRun, AICost, NodeEdge


class TestEnums:
    def test_tool_type_values(self):
        assert ToolType.LLM == 0
        assert ToolType.Endpoint == 1
        assert ToolType.Agent == 3

    def test_property_type_values(self):
        assert PropertyType.TEXT == 0
        assert PropertyType.NUMBER == 1
        assert PropertyType.BOOLEAN == 2

    def test_pipeline_status_values(self):
        assert PipelineStatusType.Pending == 0
        assert PipelineStatusType.Completed == 2
        assert PipelineStatusType.Failed == 3

    def test_endpoint_method_values(self):
        assert EndpointMethod.GET == 0
        assert EndpointMethod.POST == 1


class TestToolModel:
    def test_default_values(self):
        tool = AiTool()
        assert tool.id == ""
        assert tool.name == ""
        assert tool.type == ToolType.LLM
        assert tool.is_enabled is True
        assert tool.agent_functions == []
        assert tool.request_inputs == []

    def test_agent_function_defaults(self):
        af = AgentFunction()
        assert af.is_enabled is True
        assert af.is_deleted is False
        assert af.function_string == ""


class TestChatBotModel:
    def test_defaults(self):
        bot = ChatBot()
        assert bot.is_enabled is True
        assert bot.is_deleted is False
        assert bot.source_type == "filesystem"

    def test_chat_message_defaults(self):
        msg = ChatMessage()
        assert msg.role == "user"
        assert msg.sources == []


class TestPipelineModels:
    def test_pipeline_defaults(self):
        p = AiPipeline()
        assert p.steps == []
        assert p.inputs == []
        assert p.edges == []

    def test_pipeline_step_defaults(self):
        s = AiPipelineStep()
        assert s.status == PipelineStatusType.Pending
        assert s.is_start is False
        assert s.disabled is False
        assert s.max_retries == 1

    def test_node_edge_defaults(self):
        e = NodeEdge()
        assert e.source == ""
        assert e.target == ""


class TestAICost:
    @patch("models.pipeline.get_model_pricing")
    def test_total_cost_calculation(self, mock_pricing):
        mock_pricing.return_value = {"input_cost": 3.0, "output_cost": 15.0}
        cost = AICost(model="test", input_token_count=1000, output_token_count=500)
        # input: 3.0/1M * 1000 = 0.003, output: 15.0/1M * 500 = 0.0075
        assert abs(cost.input_cost - 0.003) < 1e-9
        assert abs(cost.output_cost - 0.0075) < 1e-9
        assert abs(cost.total_cost - 0.0105) < 1e-9

    @patch("models.pipeline.get_model_pricing")
    def test_zero_tokens(self, mock_pricing):
        mock_pricing.return_value = {"input_cost": 3.0, "output_cost": 15.0}
        cost = AICost(model="test")
        assert cost.total_cost == 0.0


class TestAiPipelineRun:
    @patch("models.pipeline.get_model_pricing")
    def test_total_cost_aggregation(self, mock_pricing):
        mock_pricing.return_value = {"input_cost": 3.0, "output_cost": 15.0}
        run = AiPipelineRun(
            steps=[
                AiPipelineStep(call_cost=[
                    AICost(model="test", input_token_count=1000, output_token_count=500),
                    AICost(model="test", input_token_count=2000, output_token_count=1000),
                ]),
                AiPipelineStep(call_cost=[
                    AICost(model="test", input_token_count=500, output_token_count=250),
                ]),
            ]
        )
        assert run.total_input_tokens == 3500
        assert run.total_output_tokens == 1750
        assert run.total_cost > 0

    @patch("models.pipeline.get_model_pricing")
    def test_empty_run_zero_cost(self, mock_pricing):
        mock_pricing.return_value = {"input_cost": 3.0, "output_cost": 15.0}
        run = AiPipelineRun()
        assert run.total_cost == 0.0
        assert run.total_input_tokens == 0
        assert run.total_output_tokens == 0
