import uuid
import os
import streamlit as st
from helper import display_text_with_images
from langchain_core.messages import HumanMessage


ANTHROPIC_API_KEY = st.secrets["anthropic"]["ANTHROPIC_API_KEY"]
st.set_page_config(page_title="SQL and Python Agent")
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY

os.environ['LANGSMITH_TRACING'] = st.secrets["langsmith"]["LANGSMITH_TRACING"]
os.environ['LANGSMITH_API_KEY'] = st.secrets["langsmith"]["LANGSMITH_API_KEY"]
os.environ['LANGSMITH_PROJECT'] = st.secrets["langsmith"]["LANGSMITH_PROJECT"]
os.environ['LANGSMITH_ENDPOINT'] = st.secrets["langsmith"]["LANGSMITH_ENDPOINT"]

@st.cache_resource
def get_graph():
    from graph import build_graph  # imported after ANTHROPIC_API_KEY is set above
    return build_graph()


graph = get_graph()

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []


def reset_conversation():
    st.session_state.messages = []
    st.session_state.thread_id = str(uuid.uuid4())   # new thread_id = fresh graph memory


st.title("MULTI AGENT HOSPITAL ASSISTANT")
st.caption("Ask a data question, request a visualization, or ask a policy/FAQ question.")

col1, col2 = st.columns([3, 1])
with col2:
    st.button("Reset Chat", on_click=reset_conversation)

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            display_text_with_images(message["content"])
        else:
            st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("Please ask your question:"):
    with st.chat_message("user", avatar="🚀"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    response = None
    for chunk in graph.stream(
        {"messages": [HumanMessage(content=prompt)]},
        config=config,
        stream_mode="updates",
    ):
        for node_update in chunk.values():
            if "messages" in node_update:
                response = node_update["messages"][-1].content

    response = response or 'Something went wrong — please try again.'

    with st.chat_message("assistant", avatar="❇️"):
        display_text_with_images(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
