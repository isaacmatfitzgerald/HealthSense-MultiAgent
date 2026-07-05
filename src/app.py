import uuid
import os
import sys
import warnings
import streamlit as st
import unidecode
import urllib.parse
from helper import display_code_plots, display_text_with_images
from llm_agent import initialize_python_agent, initialize_sql_agent
from sqlalchemy import create_engine, text


ANTHROPIC_API_KEY = st.secrets["anthropic"]["ANTHROPIC_API_KEY"]
st.set_page_config(page_title="SQL and Python Agent")


# 1. Initialize session state here.
if "db_config" not in st.session_state:
    st.session_state.db_config = {
        'USER': '',
        'PASSWORD': '',
        'HOST': 'localhost',
        'DATABASE': '',
        'PORT': '3306'
    }

if "db_connected" not in st.session_state:
    st.session_state.db_connected = False

if 'databases' not in st.session_state:
    st.session_state.databases = []


# 2. Sidebar user inputs. return True, dbs if successful, False, [] if not. (Tuple)
st.sidebar.title("DATABASE CONFIGURATION")
st.sidebar.subheader("Enter MySQL connection details:", divider=True)

user = st.sidebar.text_input("User", value=st.session_state.db_config['USER'])
password = st.sidebar.text_input("Password", type="password", value=st.session_state.db_config['PASSWORD'])
host = st.sidebar.text_input("Host", value=st.session_state.db_config['HOST'])
port = st.sidebar.text_input("Port", value=st.session_state.db_config['PORT'])


# 3. Single dynamic button label.
button_label = "Save and Connect" if not st.session_state.db_connected else "Update Connection"

def test_connection(config):
    """Check DB connectivity and, if successful, fetch all databases."""
    try:
        connection_string = (
            f"mysql+pymysql://{config['USER']}:{urllib.parse.quote_plus(config['PASSWORD'])}"
            f"@{config['HOST']}:{config['PORT']}/"
        )
        engine = create_engine(connection_string)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

            # Fetch list of databases using the SAME connection
            result = conn.execute(text("SHOW DATABASES"))
            dbs = [
                row[0] for row in result
                if row[0] not in ('sys', 'mysql', 'performance_schema', 'information_schema')
            ]
        return True, dbs
    except Exception as e:
        st.sidebar.error(f"Connection test failed: {str(e)}")
        return False, []


# 4. Single button to connect/update.
if st.sidebar.button(button_label):
    if all([user, password, host, port]):
        new_config = {
            'USER': user,
            'PASSWORD': password,
            'HOST': host,
            'PORT': port,
            # DATABASE will be selected from dropdown below, so leave it blank initially
            'DATABASE': ''
        }
        ok, db_list = test_connection(new_config)
        if ok:
            st.session_state.db_config = new_config
            st.session_state.db_connected = True
            # Store database list in session for the dropdown
            st.session_state.databases = db_list
            st.sidebar.success("Connection test successful! Please select a database.")
        else:
            st.session_state.db_connected = False
            st.session_state.databases = []
    else:
        st.sidebar.error("All fields are required")


# 5. If connected, show the databases in a dropdown for selection. Initialize the agents if the database is changed.
if st.session_state.db_connected and st.session_state.databases:
    db_choice = st.sidebar.selectbox(
        "Select Database",
        options=st.session_state.databases,
        index=st.session_state.databases.index(st.session_state.db_config['DATABASE'])
        if st.session_state.db_config['DATABASE'] in st.session_state.databases else 0
    )
    
    if db_choice and db_choice != st.session_state.db_config['DATABASE']:
        # Update the config to the selected DB
        st.session_state.db_config['DATABASE'] = str(db_choice)
        try:
            st.session_state.sql_agent = initialize_sql_agent(st.session_state.db_config)
            st.session_state.python_agent = initialize_python_agent()
            st.sidebar.success(f"Connected to {db_choice}!")
        except Exception as e:
            st.session_state.db_config['DATABASE'] = ''
            st.sidebar.error(f"Connection to {db_choice} failed: {str(e)}")


# Main page
st.title("SQL and Python Agent")
st.write("This agent can help you with SQL queries and Python code for data analysis. Configure your MySQL database connection using the sidebar.")

if st.session_state.db_connected and st.session_state.db_config['DATABASE']:
    st.write(
        f"Using database: `{st.session_state.db_config['DATABASE']}` "
        f"at `{st.session_state.db_config['HOST']}:{st.session_state.db_config['PORT']}`"
    )
else:
    st.warning("Not connected. Provide credentials and click the button in the sidebar.")


# Configure paths
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.join(current_dir, "..")
sys.path.insert(0, parent_dir)

# Set environment variables
os.environ['ANTHROPIC_API_KEY'] = ANTHROPIC_API_KEY


# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []

# Initialize agents only after credentials are available
if st.session_state.get('db_connected') and st.session_state.db_config.get('DATABASE'):
    if 'sql_agent' not in st.session_state:
        st.session_state.sql_agent = initialize_sql_agent(st.session_state.db_config)
    if 'python_agent' not in st.session_state:
        st.session_state.python_agent = initialize_python_agent()


def generate_response(response_mode, input_text):
    """Generate responses for both general and database-specific queries"""
    
    # General greetings and help messages
    greetings = ['hello', 'hi', 'hey', 'help', 'what can you do']
    if input_text.lower() in greetings:
        return """Hello! I am a SQL and Python agent designed to help you with:
            1. SQL queries and database analysis
            2. Python data visualization
            3. General database questions

            To get started with database operations, please configure your database connection in the sidebar.
            You can also ask me general questions about SQL, Python, or data analysis!
        """
    
    # Check if database is configured
    if not st.session_state.get('sql_agent'):
        return "Please configure and connect to a database using the sidebar before running queries."

    # Sanitize input
    local_prompt = unidecode.unidecode(input_text)
    
    if response_mode == "python":
        try:
            # First get SQL query result
            sql_response = st.session_state.sql_agent.invoke({"input": local_prompt})
            if not sql_response or 'output' not in sql_response:
                return "Failed to get SQL query results"
                
            local_response = sql_response['output']
            if isinstance(local_response, list):
                local_response = ' '.join(
                    item.get('text', str(item)) if isinstance(item, dict) else str(item)
                    for item in local_response
                )
            print("SQL Response->", local_response)
            
            # Check for invalid/error responses
            exclusion_keywords = ["please provide", "don't know", "more context", 
                                "provide more", "vague request", "no results"]
            if any(keyword in local_response.lower() for keyword in exclusion_keywords):
                return "Unable to generate visualization - no valid data returned from query"
            
            # Generate visualization
            viz_prompt = {"input": "Write code in python to plot the following data\n\n" + local_response}
            return st.session_state.python_agent.invoke(viz_prompt)
            
        except Exception as e:
            print(f"Error generating response: {str(e)}")
            return "Failed to generate visualization"
            
    else:  # SQL code
        try:
            sql_response = st.session_state.sql_agent.invoke({"input": local_prompt})
            output = sql_response.get('output', "Failed to get SQL query results")
            if isinstance(output, list):
                output = ' '.join(
                    item.get('text', str(item)) if isinstance(item, dict) else str(item)
                    for item in output
                )
            return output
        except Exception as e:
            print(f"SQL query error: {str(e)}")
            return """Failed to execute SQL query. Ensure you have enough Anthropic API credits. This is most likely to be the issue."""


def reset_conversation():
    st.session_state.messages = []
    st.session_state.chat_session_id = str(uuid.uuid4())   # new session ID = fresh memory
    if st.session_state.get('db_connected') and st.session_state.db_config.get('DATABASE'):
        st.session_state.sql_agent = initialize_sql_agent(st.session_state.db_config)
        st.session_state.python_agent = initialize_python_agent()
    else:
        st.warning("Please configure database credentials first")

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
    with st.chat_message("user", avatar="🚀"):
        st.markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    keywords = ["plot", "graph", "chart", "diagram", "visualize", "visualisation", "show"]
    if any(keyword in prompt.lower() for keyword in keywords):
        response = generate_response("python", prompt)

        if not isinstance(response, dict) or 'output' not in response:
            error_msg = "Please try again with a re-phrased query and more context"
            with st.chat_message("error"):
                display_text_with_images(error_msg)
            st.session_state.messages.append({"role": "error", "content": error_msg})
        else:
            code = display_code_plots(response['output'])
            if code is None:
                error_msg = "Could not extract plotting code from the response"
                with st.chat_message("error"):
                    display_text_with_images(error_msg)
                st.session_state.messages.append({"role": "error", "content": error_msg})
            else:
                try:
                    code = f"import pandas as pd\n{code.replace('fig.show()', '')}"
                    code += "st.plotly_chart(fig, theme='streamlit', use_container_width=True)"
                    exec(code)
                    st.session_state.messages.append({"role": "plot", "content": code})
                except Exception:
                    error_msg = "Please try again with a re-phrased query and more context"
                    with st.chat_message("error"):
                        display_text_with_images(error_msg)
                    st.session_state.messages.append({"role": "error", "content": error_msg})
    else:
        response = generate_response("answer", prompt)
        with st.chat_message("assistant", avatar="❇️"):
            display_text_with_images(response)
        st.session_state.messages.append({"role": "assistant", "content": response})