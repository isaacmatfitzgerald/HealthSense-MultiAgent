LLM_MODEL_NAME = "gpt-4-0125-preview"

CUSTOM_SUFFIX = """Begin!

Relevant pieces of previous conversation:
{chat_history}
(Note: Only reference this information if it is relevant to the current query.)

Question: {input}
Thought Process: It is imperative that you do not fabricate information not present in any table or engage in hallucination; maintaining trustworthiness is crucial.
In SQL queries involving string or TEXT comparisons like first_name, you must use the `LOWER()` function for case-insensitive comparisons and the `LIKE` operator for fuzzy matching. 
Queries for return percentage is defined as total number of returns divided by total number of orders. You can join orders table with users table to know more about each user.
Make sure that query is related to the SQL database and tables you are working with.
If the result is empty, the Answer should be "No results found". DO NOT hallucinate an answer if there is no result.

Your final response should STRICTLY be the output of a SQL query.

{agent_scratchpad}
"""

