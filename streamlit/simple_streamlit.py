import streamlit as st

st.set_page_config(page_title="SQL and Python Agent")

# Main Page Title
st.title("SQL and Python Agent")

# Sidebar
st.sidebar.title("DATABASE CONFIGURATION")

# Chat Input
if prompt := st.chat_input("Please ask your question:"):
   with st.chat_message("user", avatar="🚀")
     st.markdowqn(prompt)