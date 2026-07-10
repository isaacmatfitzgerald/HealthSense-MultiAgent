from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage

from constants import WORKER_MODEL
from state import AgentState

VIZ_AGENT_SYSTEM_PROMPT = """You are a data visualization assistant for a hospital analytics tool.

You will be given a natural-language description of the results of a database
query. Write Python code using Plotly (plotly.express or plotly.graph_objects)
that visualizes the data described.

Rules:
- Extract whatever numeric or categorical data is present in the input and
  choose an appropriate chart type (bar, line, or pie) for it.
- Assign the resulting figure to a variable named `fig`.
- Never call `fig.show()` — the calling application renders the figure itself.
- Always include import statements at the top of the code block (e.g.
  `import pandas as pd` and `import plotly.express as px`) — do not assume
  any libraries are pre-imported.
- Respond with ONLY a single fenced Python code block. No prose before or
  after it.
- If the input does not contain enough data to build a meaningful chart
  (e.g. it's a single number with no categories to compare), say so in a
  code comment instead of inventing data points that weren't in the input.
- For tabular data with many columns or rows, use plotly.graph_objects.Table instead of a chart.
"""

viz_llm = init_chat_model(WORKER_MODEL, temperature=0)


def viz_agent(state: AgentState) -> dict:
    response = viz_llm.invoke(
        [SystemMessage(content=VIZ_AGENT_SYSTEM_PROMPT), HumanMessage(content=state["sql_result"])]
    )
    return {"plot_code": response.content}
