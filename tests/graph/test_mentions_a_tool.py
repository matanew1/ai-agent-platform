"""Regression coverage for the recall-favoring tool-mention pre-check."""

from graph.graph import _mentions_a_tool

from shared.types import ToolDefinition


def test_matches_on_a_word_from_the_tool_name() -> None:
    tools = [ToolDefinition(name="search_emails", description="Search Gmail.", source="gmail")]

    assert _mentions_a_tool("Please search my emails from today.", tools) is True


def test_matches_on_a_word_from_the_tool_source_even_when_the_name_does_not() -> None:
    # Every Gmail tool is named around "email" (search_emails, read_email,
    # ...), not "gmail" - so a completely ordinary phrasing like "show me my
    # last 10 gmails" matched none of them by name alone and skipped tool
    # execution entirely. tool.source ("gmail", the MCP server's own name)
    # closes that gap.
    tools = [ToolDefinition(name="search_emails", description="Search Gmail.", source="gmail")]

    assert _mentions_a_tool("Show me the last 10 gmails i got.", tools) is True


def test_source_matching_is_generic_not_hardcoded_to_gmail() -> None:
    tools = [ToolDefinition(name="tavily_search", description="Search the web.", source="tavily")]

    assert _mentions_a_tool("Check tavily for the latest news.", tools) is True


def test_no_tool_mentioned_returns_false() -> None:
    tools = [ToolDefinition(name="search_emails", description="Search Gmail.", source="gmail")]

    assert _mentions_a_tool("What's the weather like today?", tools) is False


def test_the_local_source_default_is_not_treated_as_a_keyword() -> None:
    # ToolDefinition.source defaults to "local" for every in-process tool
    # (pdf, markdown, ats, ...), which are always registered - unlike a real
    # MCP server name (gmail, tavily), "local" is a generic English word
    # with no relation to what any tool does, so treating it as a keyword
    # the same way as "gmail" would make this fire on ordinary, unrelated
    # messages on effectively every turn. Regression coverage for exactly
    # that: the tool's own name doesn't match either, so this must be False.
    tools = [ToolDefinition(name="extract_pdf", description="Extract PDF text.", source="local")]

    assert _mentions_a_tool("Can you recommend a good local restaurant?", tools) is False
    assert _mentions_a_tool("I saved it locally on my machine.", tools) is False
