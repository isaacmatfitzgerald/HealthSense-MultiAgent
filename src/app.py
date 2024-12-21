import os
import sys
import warnings
import streamlit as st
import unidecode
import mysql.connector
from mysql.connector import Error
from langchain_community.utilities import SQLDatabase
import urllib.parse
from helper import display_code_plots, display_text_with_images
from llm_agent import initialize_python_agent, initialize_sql_agent
from constants import LLM_MODEL_NAME
from sqlalchemy import create_engine, exc
import pymysql
import time

OPENAI_API_KEY = st.secrets["openai"]["OPENAI_API_KEY"]

# Configure Streamlit app page
st.set_page_config(page_title="SQL and Python Agent")


# Initialize all session state variables
if 'db_config' not in st.session_state:
    st.session_state.db_config = {
        'USER': None,
        'PASSWORD': None,
        'HOST': 'localhost',
        'DATABASE': None,
        'PORT': '3306'
    }
if 'db_connection' not in st.session_state:
    st.session_state.db_connection = None
if 'agent_memory_sql' not in st.session_state:
    st.session_state.agent_memory_sql = None
if 'agent_memory_python' not in st.session_state:
    st.session_state.agent_memory_python = None
if 'connection_tested' not in st.session_state:
    st.session_state.connection_tested = False
if 'databases' not in st.session_state:
    st.session_state.databases = []

# Database configuration inputs
st.sidebar.title("MYSQL DB CONFIGURATION")
st.sidebar.subheader("Enter connection details:")

user = st.sidebar.text_input("User", 
    value=st.session_state.db_config['USER'] if st.session_state.db_config['USER'] else '')
password = st.sidebar.text_input("Password", type="password")
host = st.sidebar.text_input("Host", 
    value=st.session_state.db_config['HOST'] if st.session_state.db_config['HOST'] else 'localhost')
port = st.sidebar.text_input("Port", 
    value=st.session_state.db_config['PORT'] if st.session_state.db_config['PORT'] else '3306')

def get_databases(config):
    """Fetch available databases using connection details"""
    try:
        connection = mysql.connector.connect(
            host=config['HOST'],
            user=config['USER'],
            password=config['PASSWORD'],
            port=config['PORT']
        )
        if connection.is_connected():
            cursor = connection.cursor()
            cursor.execute("SHOW DATABASES")
            databases = [db[0] for db in cursor.fetchall()]
            cursor.close()
            connection.close()
            return databases
    except Error as e:
        st.sidebar.error(f"Error fetching databases: {e}")
        return []
    return []

# Test connection and get databases
if st.sidebar.button("Test Connection"):
    if all([user, password, host, port]):
        config = {
            'USER': user,
            'PASSWORD': password,
            'HOST': host,
            'PORT': port
        }
        st.session_state.databases = get_databases(config)
        if st.session_state.databases:
            st.sidebar.success("Connection successful! Select a database.")
    else:
        st.sidebar.error("All fields are required")

# Database dropdown (only show if databases are fetched)
if st.session_state.databases:
    database = st.sidebar.selectbox(
        "Select Database",
        options=st.session_state.databases,
        index=0 if st.session_state.databases else None
    )
    
    # Save and connect button
    if st.sidebar.button("Connect to Database"):
        st.session_state.db_config = {
            'USER': user,
            'PASSWORD': password,
            'HOST': host,
            'DATABASE': database,
            'PORT': port
        }
        try:
            st.session_state.sql_agent = initialize_sql_agent(st.session_state.db_config)
            st.session_state.python_agent = initialize_python_agent()
            st.sidebar.success(f"Connected to {database}!")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {str(e)}")

def test_connection(config):
    try:
        connection_string = (
            f"mysql+pymysql://{config['USER']}:{urllib.parse.quote_plus(config['PASSWORD'])}@"
            f"{config['HOST']}:{config['PORT']}/{config['DATABASE']}"
        )
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        st.sidebar.error(f"Connection test failed: {str(e)}")
        return False

if st.sidebar.button("Save and Connect"):
    if all([user, password, host, database, port]):
        st.session_state.db_config = {
            'USER': user,
            'PASSWORD': password,
            'HOST': host,
            'DATABASE': database,
            'PORT': port
        }
        try:
            st.session_state.sql_agent = initialize_sql_agent(st.session_state.db_config)
            st.session_state.python_agent = initialize_python_agent()
            st.sidebar.success("Connection successful!")
        except Exception as e:
            st.sidebar.error(f"Connection failed: {str(e)}")
    else:
        st.sidebar.error("All fields are required")

# Add connection management functions
def create_db_connection(config):
    """Create and return database connection"""
    try:
        connection_string = (
            f"mysql+pymysql://{config['USER']}:{config['PASSWORD']}@"
            f"{config['HOST']}:{config['PORT']}/{config['DATABASE']}"
        )
        engine = create_engine(connection_string, pool_pre_ping=True)
        db = SQLDatabase.from_uri(connection_string)
        return db
    except Exception as e:
        st.sidebar.error(f"Failed to create connection: {str(e)}")
        return None

def verify_connection():
    """Verify database connection is active"""
    if not st.session_state.get('db_config'):
        st.error("Database configuration not found")
        return False
    
    if not st.session_state.get('db_connection'):
        st.error("No active database connection")
        return False
        
    try:
        # Test connection with a simple query
        st.session_state.db_connection.run("SELECT 1")
        return True
    except:
        # Try to reconnect
        st.session_state.db_connection = create_db_connection(st.session_state.db_config)
        return st.session_state.db_connection is not None

def execute_query(query):
    """Execute query with connection verification"""
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        if verify_connection():
            try:
                result = st.session_state.db_connection.run(query)
                return result
            except exc.SQLAlchemyError as e:
                retry_count += 1
                if retry_count == max_retries:
                    st.error(f"Query failed after {max_retries} attempts: {str(e)}")
                    return None
                time.sleep(1)  # Wait before retry
        else:
            st.error("Connection verification failed")
            return None

# Suppress warnings
warnings.filterwarnings("ignore")

# Configure paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.join(current_dir, "..")
sys.path.insert(0, parent_dir)

# Set environment variables
os.environ['OPENAI_API_KEY'] = OPENAI_API_KEY


# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Initialize agents only after credentials are available
if 'db_config' in st.session_state:
    if 'agent_memory_sql' not in st.session_state:
        st.session_state.agent_memory_sql = initialize_sql_agent(st.session_state.db_config)
    if 'agent_memory_python' not in st.session_state:
        st.session_state.agent_memory_python = initialize_python_agent()
    
    if 'sql_agent' not in st.session_state:
        st.session_state.sql_agent = st.session_state.agent_memory_sql
    if 'python_agent' not in st.session_state:
        st.session_state.python_agent = st.session_state.agent_memory_python
else:
    st.warning("Please configure database credentials first")


def generate_response(code_type, input_text):
    """Generate responses for both general and database-specific queries"""
    
    # General greetings and help messages
    greetings = ['hello', 'hi', 'hey', 'help', 'what can you do']
    if input_text.lower() in greetings:
        return """Hello! I am a SQL and Python agent designed to help you with:
        
1. SQL queries and database analysis
2. Python data visualization
3. General database questions

To get started with database operations, please configure your database connection in the sidebar.
You can also ask me general questions about SQL, Python, or data analysis!"""
    
    # Check if database is configured
    if not st.session_state.get('sql_agent'):
        return "Please configure and connect to a database using the sidebar before running queries."
    
    # Sanitize input
    local_prompt = unidecode.unidecode(input_text)
    
    if code_type == "python":
        try:
            # First get SQL query result
            sql_response = st.session_state.sql_agent.invoke({"input": local_prompt})
            if not sql_response or 'output' not in sql_response:
                return "Failed to get SQL query results"
                
            local_response = sql_response['output']
            print("SQL Response->", local_response)
            
            # Check for invalid/error responses
            exclusion_keywords = ["please provide", "don't know", "more context", 
                                "provide more", "vague request", "no results"]
            if any(keyword in local_response.lower() for keyword in exclusion_keywords):
                return "Unable to generate visualization - no valid data returned from query"
            
            # Generate visualization
            viz_prompt = {"input": "Write a code in python to plot the following data\n\n" + local_response}
            return st.session_state.python_agent.invoke(viz_prompt)
            
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return "Failed to generate visualization"
            
    else:  # SQL query
        try:
            return st.session_state.sql_agent.run(local_prompt)
        except Exception as e:
            print(f"SQL query error: {str(e)}")
            return "Failed to execute SQL query"


def reset_conversation():
    st.session_state.messages = []
    if 'db_config' in st.session_state:
        st.session_state.agent_memory_sql = initialize_sql_agent(st.session_state.db_config)
        st.session_state.agent_memory_python = initialize_python_agent()
        st.session_state.sql_agent = st.session_state.agent_memory_sql
        st.session_state.python_agent = st.session_state.agent_memory_python
    else:
        st.warning("Please configure database credentials first")


# Display title and description
st.title("SQL and Python Agent")
st.write("This agent can help you with SQL queries and Python code for data analysis. Configure your MySQL database connection using the sidebar.")

# Display connection status
if "db_config" in st.session_state:
    db_config = st.session_state.db_config
    st.write(f"Using database: `{db_config['DATABASE']}` at `{db_config['HOST']}:{db_config['PORT']}`")
else:
    st.warning("Please save your database credentials in the sidebar.")

col1, col2 = st.columns([3, 1])
with col2:
    st.button("Reset Chat", on_click=reset_conversation)

# Display chat messages from history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        if message["role"] in ("assistant", "error"):
            display_text_with_images(message["content"])
        elif message["role"] == "plot":
            exec(message["content"])
        else:
            st.markdown(message["content"])

# Accept user input
if prompt := st.chat_input("Please ask your question:"):
    # Display user message in chat
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})
    keywords = ["plot", "graph", "chart", "diagram"]
    if any(keyword in prompt.lower() for keyword in keywords):
        prev_context = ""
        for msg in reversed(st.session_state.messages):
            if msg["role"] == "assistant":
                prev_context = msg["content"] + "\n\n" + prev_context
                break
        if prev_context:
            prompt += f"\n\nGiven previous agent responses:\n{prev_context}\n"
        response = generate_response("python", prompt)
        if response == "NO_RESPONSE":
            response = "Please try again with a re-phrased query and more context"
            with st.chat_message("error"):
                display_text_with_images(response)
            st.session_state.messages.append({"role": "error", "content": response})
        else:
            code = display_code_plots(response['output'])
            try:
                code = f"import pandas as pd\n{code.replace('fig.show()', '')}"
                code += "st.plotly_chart(fig, theme='streamlit', use_container_width=True)"
                exec(code)
                st.session_state.messages.append({"role": "plot", "content": code})
            except:
                response = "Please try again with a re-phrased query and more context"
                with st.chat_message("error"):
                    display_text_with_images(response)
                st.session_state.messages.append({"role": "error", "content": response})
    else:
        if len(st.session_state.messages) > 1:
            context_length = 0
            prev_context = ""
            for msg in reversed(st.session_state.messages):
                if context_length > 1:
                    break
                if msg["role"] == "assistant":
                    prev_context = msg["content"] + "\n\n" + prev_context
                    context_length += 1
            response = generate_response("sql", f"{prompt}\n\nGiven previous agent responses:\n{prev_context}\n")
        else:
            response = generate_response("sql", prompt)
        with st.chat_message("assistant"):
            display_text_with_images(response)
        st.session_state.messages.append({"role": "assistant", "content": response})

# Initialize session state for query
if 'query' not in st.session_state:
    st.session_state.query = ''

# Initialize session state with unique widget keys
if 'query_input_key' not in st.session_state:
    st.session_state.query_input_key = 0
