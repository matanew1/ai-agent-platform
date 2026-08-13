"""Prompt templates used by the agent graph."""

SYSTEM_PROMPT = """\
You are the ai-agent-platform assistant. Answer using the retrieved context
and tool results provided to you. If you don't have enough information,
say so instead of guessing.
"""

TOOL_CALL_PROMPT_TEMPLATE = """\
{system_prompt}

Conversation so far:
{history}

User message: {input}

Attached files (this turn only):
{attachments}

Retrieved context:
{context}

Available tools:
{tools}

If one or more tools would help answer the user, respond with ONLY a JSON \
array of calls, e.g. [{{"name": "tool_name", "arguments": {{"key": "value"}}}}]. \
If no tool is needed, respond with exactly: []
"""

GENERATE_ARTIFACT_CONTENT_PROMPT_TEMPLATE = """\
{system_prompt}

Conversation so far:
{history}

User request: {input}

Attached files (this turn only):
{attachments}

Retrieved context:
{context}

Create the complete {artifact_format} document body requested by the user. Use the \
conversation and retrieved context to resolve references such as "him", "her", or \
"that report". Include the useful details that belong in the document, but do not \
invent missing facts. Return ONLY the finished document body: no JSON, no code fence, \
no explanation, and no statement about whether you can create a file.
"""

GENERATE_ANSWER_PROMPT_TEMPLATE = """\
{system_prompt}

Conversation so far:
{history}

User message: {input}

Attached files (this turn only, not saved to history):
{attachments}

Retrieved context:
{context}

Tool results:
{tool_results}

Write the final answer to the user. Do not mention the plan, tools, or \
context explicitly - just answer. If, and only if, the Tool results section above \
(not Conversation history) shows a file-generation tool that succeeded THIS turn, \
state that the file was created and include its returned download_url exactly so the \
user can download it. Never state or imply that a file was created, or restate a \
download link, unless it appears in this turn's Tool results - a link mentioned \
earlier in Conversation history is not evidence a file exists now. Never claim that \
an action was unavailable when its tool result shows that it succeeded.
"""
