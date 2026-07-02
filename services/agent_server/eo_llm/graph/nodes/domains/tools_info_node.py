"""Tools discovery domain node.

Delegates to the MCP ``tools_info_tool`` so the graph pipeline shares the same
catalog, formatting, and per-tool/category lookup logic as the legacy DataAgent.
"""

from __future__ import annotations

from eo_llm.adapters.mcp_client import call_mcp_tool
from eo_llm.graph.state import GraphState, validate_state


def _is_scoped_tools_query(query: str) -> bool:
    """True when the user asks about tools for a specific topic, not the full catalog."""
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


def _tools_info_arguments(user_query: str) -> dict[str, object]:
    """Map the user utterance to ``tools_info_tool`` parameters."""
    q = (user_query or "").strip()
    q_lower = q.lower()

    if _is_scoped_tools_query(q):
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


def tools_info_node(state: GraphState) -> GraphState:
    s = validate_state(state)
    if "tools_info" not in set(s.selected_domains):
        return {}

    user_q = (s.user_query or "").strip()
    if not user_q:
        return {}

    tool_args = _tools_info_arguments(user_q)

    try:
        result = call_mcp_tool("tools_info_tool", tool_args)
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
                "tools_info": {
                    "status": "error",
                    "message": message,
                    "error": True,
                }
            },
        }

    message = str(result.get("message") or "").strip()
    if not message:
        message = "No tools information was returned."

    return {
        "final_answer": message,
        "next_step": "finalize_direct",
        "answer_source": "domain_tools",
        "domain_results": {
            "tools_info": {
                "status": "done" if not result.get("error") else "error",
                "tool": "tools_info_tool",
                "arguments": tool_args,
                "result": result,
                "message": message,
                "summary": {"successful_steps": 0 if result.get("error") else 1},
                "error": bool(result.get("error")),
            }
        },
    }
