import streamlit as st

st.set_page_config(page_title="SQL and Python Agent")
# MAIN PAGE
st.title("SQL and Python Agent")

# SIDE BAR
st.sidebar.title("DATABASE CONFIGURATION")
st.sidebar.subheader("Enter MySQL connection details:", divider=True)


# CHAT INPUT
if prompt := st.chat_input("Please ask your question:"):
   with st.chat_message("user", avatar="🚀"):
     st.markdown(prompt)