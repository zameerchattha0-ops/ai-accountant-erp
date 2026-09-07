"""
ERP AI Agent — Gemini Client
==============================
Handles all communication with Google Gemini via the ``google-genai`` SDK.

Responsibilities:
* Initialise the Gemini API client
* Construct system instructions from the Constitution
* Inject runtime context
* Provide tool definitions for function-calling
* Execute iterative tool-call loops
* Handle structured responses, errors, retries

The client does NOT know arbitrary ERP business logic — that belongs to
the Planner, Tools, Services, Validator, and Accounting Engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from google.genai import Client
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.database import get_gemini_api_key
from app.models.schemas import AgentContext, ToolCall, ToolResult
from app.prompts import build_system_instructions, build_user_content, load_constitution
from app.tool_execution import execute_planned_tool_calls
from app.tool_router import get_gemini_tool_definitions

log = structlog.get_logger(__name__)

# Module-level singleton
_client: Optional["GeminiClient"] = None


class GeminiClient:
    """Wrapper around the google-genai SDK for the ERP agent."""

    def __init__(self) -> None:
        settings = get_settings()
        api_key = get_gemini_api_key()
        self._gclient = Client(api_key=api_key)

        self.model_name = settings.gemini_model
        self.temperature = settings.gemini_temperature
        self.max_output_tokens = settings.gemini_max_output_tokens
        self.top_p = settings.gemini_top_p
        self.top_k = settings.gemini_top_k

        # Load Constitution
        self._constitution = self._load_constitution()

        # System instructions (constant across all requests)
        self._system_instructions = self._build_system_instructions()

        log.info(
            "gemini_client.initialised",
            model=self.model_name,
            constitution_chars=len(self._constitution),
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def generate_with_tools(
        self,
        *,
        user_message: str,
        context: AgentContext,
        max_tool_iterations: int = 10,
        executor: Optional[Any] = None,
        excluded_tools: Optional[set] = None,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Send a message to Gemini with tool-calling support.

        When *executor* is provided (an async callable
        ``(tool_name, args) -> dict``), tools are executed internally
        and results are fed back to Gemini for multi-turn reasoning.
        When omitted, tool calls are returned to the caller for
        external execution.

        ``excluded_tools`` removes deterministically disabled tools from the
        offered set (see QwenClient.generate_with_tools).

        Returns ``{"text": str, "tool_calls": [ToolCall, ...],
        "tool_results": [ToolResult, ...]}``.
        """
        # Build user content
        user_content = self._build_user_content(user_message, context)

        # Tool definitions for Gemini (reads ai.tool_parameters from DB)
        tool_defs = await get_gemini_tool_definitions()
        if excluded_tools:
            tool_defs = [
                td for td in tool_defs if td.get("name") not in excluded_tools
            ]
        tools_list = self._to_gemini_tools(tool_defs) if tool_defs else None

        # Generation config (includes system_instruction + tools).
        # ``max_output_tokens`` overrides the client default for THIS
        # request (Work Stream B tiered routing: lighter budget for simple
        # lookups that still need the model).
        config = types.GenerateContentConfig(
            system_instruction=self._system_instructions,
            temperature=self.temperature,
            max_output_tokens=max_output_tokens or self.max_output_tokens,
            top_p=self.top_p,
            top_k=int(self.top_k),
            tools=tools_list,
            # Disable automatic function calling — we manage the loop manually.
            # (google-genai >= 2.x removed `maximum_iterations`; `disable` is
            # the supported switch.)
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True,
            ),
        )

        # Create chat session
        chat = self._gclient.chats.create(
            model=self.model_name,
            config=config,
        )

        # Send message
        response = chat.send_message(message=user_content)

        # Process response — handle tool calls iteratively
        all_tool_calls: List[ToolCall] = []
        tool_results: list = []
        iteration = 0
        text_parts: List[str] = []

        while iteration < max_tool_iterations:
            iteration += 1

            # Check if Gemini wants to call a tool
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                has_function_call = False
                iteration_tool_calls: list[ToolCall] = []

                for part in response.candidates[0].content.parts:
                    if part.function_call:
                        has_function_call = True
                        fc = part.function_call
                        tc = ToolCall(
                            tool_name=fc.name,
                            arguments=dict(fc.args) if fc.args else {},
                        )
                        iteration_tool_calls.append(tc)
                        all_tool_calls.append(tc)

                    if part.text:
                        text_parts.append(part.text)

                # Execute tools and feed results back to Gemini.
                # Work Stream A1: independent read-only calls run
                # CONCURRENTLY; mutations stay strictly sequential in plan
                # order (see app/tool_execution.py).
                if has_function_call and executor:
                    result_data_list = await execute_planned_tool_calls(
                        iteration_tool_calls, executor
                    )
                    function_responses: list = []
                    for tc, result_data in zip(
                        iteration_tool_calls, result_data_list
                    ):
                        log.info(
                            "gemini_client.tool_call",
                            tool=tc.tool_name,
                            iteration=iteration,
                        )
                        tool_results.append(
                            ToolResult(
                                tool_name=tc.tool_name,
                                success=(
                                    result_data.get("success", True)
                                    if isinstance(result_data, dict)
                                    else True
                                ),
                                data=result_data if isinstance(result_data, dict) else None,
                                error=(
                                    result_data.get("error")
                                    if isinstance(result_data, dict)
                                    else None
                                ),
                            )
                        )

                        function_responses.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=tc.tool_name,
                                    response={
                                        "result": (
                                            result_data
                                            if isinstance(result_data, dict)
                                            else {"data": str(result_data)}
                                        ),
                                    },
                                )
                            )
                        )

                    # Send function responses back to Gemini
                    response = chat.send_message(message=function_responses)
                    continue  # Process the next response

                if not has_function_call:
                    break  # Final text-only response — done
            else:
                break

        result_text = "\n".join(text_parts) if text_parts else ""
        return {
            "text": result_text,
            "tool_calls": all_tool_calls,
            "tool_results": tool_results,
            "iteration_count": iteration,
        }

    async def generate_text(
        self,
        *,
        prompt: str,
        context: Optional[AgentContext] = None,
    ) -> str:
        """Simple text generation without tool-calling."""
        config = types.GenerateContentConfig(
            system_instruction=self._system_instructions,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        user_content = prompt
        if context:
            user_content = self._build_user_content(prompt, context)

        response = self._gclient.models.generate_content(
            model=self.model_name,
            contents=user_content,
            config=config,
        )
        return response.text if response.text else ""

    # -------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------

    def _load_constitution(self) -> str:
        """Load the ERP_AGENT_CONSTITUTION.md from disk (shared module)."""
        return load_constitution()

    def _build_system_instructions(self) -> str:
        """Build the permanent system instructions (shared module)."""
        return build_system_instructions(self._constitution)

    def _build_user_content(self, message: str, context: AgentContext) -> str:
        """Build the user message with relevant runtime context (shared module)."""
        return build_user_content(message, context)

    # JSON-Schema / ai.tool_parameters data_type → Gemini Type enum
    _TYPE_MAP = {
        "string": types.Type.STRING,
        "integer": types.Type.INTEGER,
        "number": types.Type.NUMBER,
        "boolean": types.Type.BOOLEAN,
        "array": types.Type.ARRAY,
        "object": types.Type.OBJECT,
    }

    def _to_gemini_tools(self, tool_defs: List[Dict[str, Any]]) -> List[types.Tool]:
        """Convert our tool definitions to Gemini function declarations.

        Properly maps JSON-Schema types (string, integer, number,
        boolean, array, object) instead of treating everything as STRING.
        """
        functions = []
        for td in tool_defs:
            props = td.get("parameters", {}).get("properties", {})
            required_list = td.get("parameters", {}).get("required", [])
            functions.append(
                types.FunctionDeclaration(
                    name=td["name"],
                    description=td.get("description", ""),
                    # Omit parameters entirely for parameter-less tools —
                    # an OBJECT Schema with empty properties is invalid.
                    parameters=(
                        types.Schema(
                            type=types.Type.OBJECT,
                            properties={
                                k: types.Schema(
                                    type=self._TYPE_MAP.get(
                                        v.get("type", "string"),
                                        types.Type.STRING,
                                    ),
                                    description=v.get("description", ""),
                                    # Gemini requires an `items` schema for
                                    # ARRAY parameters. ai.tool_parameters
                                    # stores only the data_type, so declare
                                    # free-form objects as the element type.
                                    items=(
                                        types.Schema(type=types.Type.OBJECT)
                                        if v.get("type", "") == "array"
                                        else None
                                    ),
                                )
                                for k, v in props.items()
                            },
                            required=required_list if required_list else None,
                        )
                        if props
                        else None
                    ),
                )
            )
        return [types.Tool(function_declarations=functions)] if functions else []


def get_client() -> GeminiClient:
    """Return or create the singleton GeminiClient."""
    global _client
    if _client is None:
        _client = GeminiClient()
    return _client
