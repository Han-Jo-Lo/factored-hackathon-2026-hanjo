
#from middleware.observability import observability_model, observability_tool
from middleware.routing import  model_fallback
from middleware.summarization import context_summarizer
from middleware.security import tool_authorization, sanitize_tool_output
from middleware.retry import retry_tool

ALL_MIDDLEWARE = [
    #observability_model,
    model_fallback,
    context_summarizer,
    #observability_tool,
    tool_authorization,
    retry_tool,
    sanitize_tool_output,
]
