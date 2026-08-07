"""Prompt templates used by the agent graph."""

SYSTEM_PROMPT = """\
You are the ai-agent-platform assistant. Answer using the retrieved context
and tool results provided to you. If you don't have enough information,
say so instead of guessing.
"""

TOOL_CALL_PROMPT_TEMPLATE = """\
{system_prompt}

User message: {input}

Available tools:
{tools}

If one or more tools would help answer the user, respond with ONLY a JSON \
array of calls, e.g. [{{"name": "tool_name", "arguments": {{"key": "value"}}}}]. \
If no tool is needed, respond with exactly: []
"""

GENERATE_ANSWER_PROMPT_TEMPLATE = """\
{system_prompt}

Conversation so far:
{history}

User message: {input}

Retrieved context:
{context}

Tool results:
{tool_results}

Write the final answer to the user. Do not mention the plan, tools, or \
context explicitly - just answer.
"""
