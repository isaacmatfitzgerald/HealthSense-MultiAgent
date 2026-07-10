import re 
import uuid
import os
import streamlit as st
from langchain_core.messages import HumanMessage
from langgraph.types import Command
import logging
import warnings
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("transformers.utils.import_utils").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=".*torchvision.*")


def display_code_plots(text):
    pattern = r'```python\s(.*?)```'
    matches = re.findall(pattern, text, re.DOTALL)
    if not matches:
        return None
    else:
        return matches[0]

ANTHROPIC_API_KEY = st.secrets["anthropic"]["ANTHROPIC_API_KEY"]
st.set_page_config(page_title="SQL and Python Agent")
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY

os.environ['LANGSMITH_TRACING'] = st.secrets["langsmith"]["LANGSMITH_TRACING"]
os.environ['LANGSMITH_API_KEY'] = st.secrets["langsmith"]["LANGSMITH_API_KEY"]
os.environ['LANGSMITH_PROJECT'] = st.secrets["langsmith"]["LANGSMITH_PROJECT"]
os.environ['LANGSMITH_ENDPOINT'] = st.secrets["langsmith"]["LANGSMITH_ENDPOINT"]

os.environ['MYSQL_READER_HOST'] = st.secrets["mysql"]["MYSQL_READER_HOST"]
os.environ['MYSQL_READER_PORT'] = st.secrets["mysql"]["MYSQL_READER_PORT"]
os.environ['MYSQL_READER_USER'] = st.secrets["mysql"]["MYSQL_READER_USER"]
os.environ['MYSQL_READER_PASSWORD'] = st.secrets["mysql"]["MYSQL_READER_PASSWORD"]
os.environ['MYSQL_READER_DATABASE'] = st.secrets["mysql"]["MYSQL_READER_DATABASE"]

os.environ['MYSQL_WRITER_HOST'] = st.secrets["mysql"]["MYSQL_WRITER_HOST"]
os.environ['MYSQL_WRITER_PORT'] = st.secrets["mysql"]["MYSQL_WRITER_PORT"]
os.environ['MYSQL_WRITER_USER'] = st.secrets["mysql"]["MYSQL_WRITER_USER"]
os.environ['MYSQL_WRITER_PASSWORD'] = st.secrets["mysql"]["MYSQL_WRITER_PASSWORD"]
os.environ['MYSQL_WRITER_DATABASE'] = st.secrets["mysql"]["MYSQL_WRITER_DATABASE"]

@st.cache_resource
def get_graph():
    from graph import build_graph  # imported after ANTHROPIC_API_KEY is set above
    return build_graph()


graph = get_graph()

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())

if "messages" not in st.session_state:
    st.session_state.messages = []

if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = None


def reset_conversation():
    st.session_state.messages = []
    st.session_state.thread_id = str(uuid.uuid4())   # new thread_id = fresh graph memory
    st.session_state.pending_confirmation = None


st.title("MULTI AGENT HOSPITAL ASSISTANT")
st.caption("Ask a data question, request a visualization, or ask a policy/FAQ question.")

col1, col2 = st.columns([3, 1])
with col2:
    st.button("Reset Chat", on_click=reset_conversation)

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            st.markdown(message["content"])
        elif message["role"] == "plot":
            exec(message["content"])
        else:
            st.markdown(message["content"])



def _consume_stream(stream):
    response = None
    plot_code = None
    interrupt_value = None
    for chunk in stream:
        if "__interrupt__" in chunk:
            interrupt_value = chunk["__interrupt__"][0].value
            continue
        for node_update in chunk.values():
            if "messages" in node_update:
                print("LAST AI MSG:", [m for m in node_update["messages"] if m.__class__.__name__ == "AIMessage"])  # add this
                for msg in reversed(node_update["messages"]):
                    if msg.__class__.__name__ == "AIMessage":
                        response = msg.content
                        break
            if "plot_code" in node_update:
                plot_code = node_update["plot_code"]
    return response, plot_code, interrupt_value


def _display_response(response, plot_code):
    response = response or 'Something went wrong — please try again.'
    if not plot_code:
        with st.chat_message("assistant", avatar="❇️"):
            st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
    if plot_code:
        code = display_code_plots(plot_code)
        if code:
            code = code.replace("fig.show()", "")
            code += "\nst.plotly_chart(fig, theme='streamlit', use_container_width=True)"
            try:
                with st.chat_message("plot"):
                    exec(code)
                st.session_state.messages.append({"role": "plot", "content": code})
            except Exception:
                with st.chat_message("error"):
                    st.markdown("Could not render the chart for this data.")


# Accept user input
# Accept user input
config = {"configurable": {"thread_id": st.session_state.thread_id}}

if st.session_state.pending_confirmation:
    details = st.session_state.pending_confirmation
    with st.chat_message("assistant", avatar="❇️"):
        st.markdown(
            "Please confirm this appointment:\n\n"
            f"- **Doctor:** {details['doctor_name']}\n"
            f"- **Date:** {details['date']} at {details['time_slot']}\n"
            f"- **Type:** {details['appointment_type']} ({details['consultation_mode']})\n"
            f"- **Patient:** {details['patient_name']} ({details['patient_email']})"
        )
        col_confirm, col_cancel = st.columns(2)
        confirmed = col_confirm.button("Confirm")
        cancelled = col_cancel.button("Cancel")

    if confirmed or cancelled:
        st.session_state.pending_confirmation = None
        response, plot_code, interrupt_value = _consume_stream(
            graph.stream(Command(resume=confirmed), config=config, stream_mode="updates")
        )
        if interrupt_value:
            st.session_state.pending_confirmation = interrupt_value
        else:
            _display_response(response, plot_code)
        st.rerun()

elif prompt := st.chat_input("Please ask your question:"):
    with st.chat_message("user", avatar="🚀"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    response, plot_code, interrupt_value = _consume_stream(
        graph.stream({"messages": [HumanMessage(content=prompt)]}, config=config, stream_mode="updates")
    )
    if interrupt_value:
        st.session_state.pending_confirmation = interrupt_value
        st.rerun()
    else:
        print("RESPONSE TO DISPLAY:", response)
        print("PLOT CODE:", plot_code)
        _display_response(response, plot_code)
