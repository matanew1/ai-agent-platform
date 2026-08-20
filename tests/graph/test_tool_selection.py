"""Regression coverage for compact explicit-tool routing."""

from graph.graph import _explicitly_named_tools, _gmail_inbox_tools

from shared.types import ToolDefinition


def test_explicit_tool_names_narrow_the_routing_menu() -> None:
    tools = [
        ToolDefinition(name="search_emails", description="Search Gmail."),
        ToolDefinition(name="read_email", description="Read a Gmail message."),
        ToolDefinition(name="tavily_search", description="Search the web."),
    ]

    selected = _explicitly_named_tools(
        "Use the search_emails tool, then read_email for important messages.", tools
    )

    assert [tool.name for tool in selected] == ["search_emails", "read_email"]


def test_no_explicit_name_preserves_the_full_menu() -> None:
    tools = [ToolDefinition(name="search_emails", description="Search Gmail.")]

    assert _explicitly_named_tools("Summarize my unread messages.", tools) == []


def test_gmail_inbox_request_keeps_only_search_and_read_tools() -> None:
    tools = [
        ToolDefinition(name="search_emails", description="Search Gmail."),
        ToolDefinition(name="read_email", description="Read a Gmail message."),
        ToolDefinition(name="delete_email", description="Delete a Gmail message."),
    ]

    selected = _gmail_inbox_tools("Summarize unread emails from the last 24 hours.", tools)

    assert [tool.name for tool in selected] == ["search_emails", "read_email"]
