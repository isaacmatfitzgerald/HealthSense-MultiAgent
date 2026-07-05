import os
import urllib.parse
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_classic.memory import ConversationBufferMemory
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_experimental.tools import PythonREPLTool
from langchain_anthropic import ChatAnthropic
from constants import LLM_MODEL_NAME
import streamlit as st
import uuid        # add this new import

CHAT_HISTORY_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_history.db")

SQL_AGENT_INSTRUCTIONS = """You are an agent designed to interact with a SQL database.
It is imperative that I do not fabricate information not present in any table or engage in hallucination; maintaining trustworthiness is crucial.
In SQL queries involving string or TEXT comparisons like first_name, I must use the LOWER() function for case-insensitive comparisons and the LIKE operator for fuzzy matching.
Queries for return percentage is defined as total number of returns divided by total number of orders. You can join orders table with users table to know more about each user.
Make sure that query is related to the SQL database and tables you are working with.
If the result is empty, the Answer should be "No results found". DO NOT hallucinate an answer if there is no result.

My final response should STRICTLY be the output of the SQL query.
"""

ANTHROPIC_API_KEY = st.secrets["anthropic"]["ANTHROPIC_API_KEY"]
os.environ.setdefault("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY)


def get_chat_anthropic(model_name: str) -> ChatAnthropic:
    return ChatAnthropic(
        model_name=model_name,
        temperature=0,
        timeout=None,
        stop=None,
    )


def initialize_python_agent(agent_llm_name: str = LLM_MODEL_NAME):
    instructions = """You are an agent designed to write python code to answer questions.
            You have access to a python REPL, which you can use to execute python code.
            If you get an error, debug your code and try again.
            You might know the answer without running any code, but you should still run the code to get the answer.
            If it does not seem like you can write code to answer the question, just return "I don't know" as the answer.
            Always output the python code only.
            Generate the code <code> for plotting the previous data in plotly, in the format requested. 
            The solution should be given using plotly and only plotly. Do not use matplotlib.
            Return the code <code> in the following
            format ```python <code>```
            """
    prompt = ChatPromptTemplate.from_messages([
        ("system", instructions),
        MessagesPlaceholder("chat_history", optional=True),
        ("human", "{input}"),
        MessagesPlaceholder("agent_scratchpad"),
    ])
    tools = [PythonREPLTool()]
    llm = get_chat_anthropic(agent_llm_name)
    agent = create_tool_calling_agent(llm, tools, prompt)
    return AgentExecutor(agent=agent, tools=tools, verbose=True)


def initialize_sql_agent(db_config, agent_llm_name: str = LLM_MODEL_NAME):
    """Initialize SQL agent with proper validation"""
    required_fields = ['USER', 'PASSWORD', 'HOST', 'DATABASE', 'PORT']

    if not db_config or not isinstance(db_config, dict):
        raise ValueError("Invalid database configuration")

    for field in required_fields:
        if field not in db_config or not db_config[field]:
            raise ValueError(f"Missing required field: {field}")

    try:
        llm = get_chat_anthropic(agent_llm_name)

        password = urllib.parse.quote_plus(db_config['PASSWORD'])
        connection_string = (
            f"mysql+pymysql://{db_config['USER']}:{password}@"
            f"{db_config['HOST']}:{db_config['PORT']}/{db_config['DATABASE']}"
        )

        db = SQLDatabase.from_uri(connection_string)
        toolkit = SQLDatabaseToolkit(db=db, llm=llm)
        tools = toolkit.get_tools()

        if "chat_session_id" not in st.session_state:
            st.session_state.chat_session_id = str(uuid.uuid4())

        message_history = SQLChatMessageHistory(
            session_id=st.session_state.chat_session_id,
            connection_string=f"sqlite:///{CHAT_HISTORY_DB_PATH}",
            table_name="message_store",
        )
        memory = ConversationBufferMemory(
            memory_key="chat_history",
            input_key='input',
            chat_memory=message_history,
            return_messages=True,   # required: MessagesPlaceholder needs message objects, not a raw string
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", SQL_AGENT_INSTRUCTIONS),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])

        agent = create_tool_calling_agent(llm, tools, prompt)
        return AgentExecutor(
            agent=agent,
            tools=tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True,
        )
    except Exception as e:
        raise ValueError(f"Failed to initialize SQL agent: {str(e)}")