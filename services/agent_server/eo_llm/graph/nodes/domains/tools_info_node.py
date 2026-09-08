"""Tools discovery domain node.

Delegates to the MCP ``tools_info_tool`` so the graph pipeline shares the same
catalog, formatting, and per-tool/category lookup logic.
"""

from __future__ import annotations

from eo_llm.adapters.mcp_client import MCPClient
from eo_llm.graph.nodes.domain_base import DomainNode
from eo_llm.graph.state import GraphState, GraphStateModel


class ToolsInfoDomainNode(DomainNode):
    """Return the MCP tools catalog and finalize without LLM composition."""

    domain_name = "tools_info"

    async def execute(self, s: GraphStateModel) -> GraphState:
        user_q = (s.user_query or "").strip()
        if not user_q:
            return {}

        tool_args = self._tools_info_arguments(user_q)

        try:
            result = await MCPClient().call_mcp_tool("tools_info_tool", tool_args)
        except Exception as exc:
            message = (
                "I couldn't retrieve the tools catalog because the MCP server is "
                f"unavailable ({exc}). Please ensure the MCP server is running."
            )
            return {
                "final_answer": message,
                "next_step": "finalize_direct",
                "answer_source": "domain_tools",
                "domain_results": {
                    self.domain_name: {
                        "status": "error",
                        "message": message,
                        "error": True,
                    }
                },
            }

        message = (result.message or "").strip() or "No tools information was returned."
        return {
            "final_answer": message,
            "next_step": "finalize_direct",
            "answer_source": "domain_tools",
            "domain_results": {
                self.domain_name: {
                    "status": "done" if not result.error else "error",
                    "tool": "tools_info_tool",
                    "arguments": tool_args,
                    "result": result.model_dump(mode="python"),
                    "message": message,
                    "summary": {"successful_steps": 0 if result.error else 1},
                    "error": result.error,
                }
            },
        }

    @staticmethod
    def _is_scoped_tools_query(query: str) -> bool:
        q = f" {(query or '').lower().strip()} "
        scoped_markers = (
            " about ",
            " for ",
            " related to ",
            " involving ",
            " that can ",
            " that help ",
            " to detect ",
            " to help ",
            " can detect ",
            " can help ",
            " with ",
        )
        return any(marker in q for marker in scoped_markers)

    def _tools_info_arguments(self, user_query: str) -> dict[str, object]:
        q = (user_query or "").strip()
        q_lower = q.lower()

        if self._is_scoped_tools_query(q):
            return {"query": q}

        list_all_markers = (
            "list all",
            "all tools",
            "available tools",
            "what tools",
            "which tools",
            "tools do you have",
            "what can you do",
            "your capabilities",
            "show me your tools",
            "show me the tools",
        )
        if any(marker in q_lower for marker in list_all_markers):
            return {"list_all": True}

        return {"query": q}


tools_info_node = ToolsInfoDomainNode()
