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


def test_explicitly_named_tools_cannot_admit_a_tool_outside_the_authorized_set() -> None:
    # The caller's already-authorized `tools` list is the only thing this
    # function ever filters - naming an unauthorized tool in the request
    # text must not conjure it into the routing menu.
    tools = [ToolDefinition(name="search_emails", description="Search Gmail.")]

    selected = _explicitly_named_tools("Please call delete_email on that message.", tools)

    assert selected == []


def test_mutating_gmail_requests_are_not_narrowed_to_search_and_read() -> None:
    # A mutating request must keep the full menu so delete_email/modify_email
    # actually reach the routing prompt - regression coverage for a bug where
    # "unread"/"inbox" doubled as both topic and action words, so any request
    # naming that topic satisfied the old heuristic regardless of intent.
    tools = [
        ToolDefinition(name="search_emails", description="Search Gmail."),
        ToolDefinition(name="read_email", description="Read a Gmail message."),
        ToolDefinition(name="delete_email", description="Delete a Gmail message."),
    ]
    mutating_requests = [
        "Delete my unread emails from yesterday.",
        "Mark my unread emails as read.",
        "Empty my inbox.",
        "Archive all messages in my inbox.",
    ]

    for request in mutating_requests:
        assert _gmail_inbox_tools(request, tools) == [], request


def test_read_only_gmail_requests_still_narrow_despite_containing_read_as_a_substring() -> None:
    # "unread" contains the substring "read" - confirms the fix tokenizes
    # into whole words instead of falling back to substring containment,
    # which would otherwise make "read" match inside "unread" by accident.
    tools = [
        ToolDefinition(name="search_emails", description="Search Gmail."),
        ToolDefinition(name="read_email", description="Read a Gmail message."),
    ]

    selected = _gmail_inbox_tools("Please read my emails from today.", tools)

    assert [tool.name for tool in selected] == ["search_emails", "read_email"]
