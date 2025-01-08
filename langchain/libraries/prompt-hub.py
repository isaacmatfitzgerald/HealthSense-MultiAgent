from langchain import hub
prompt = hub.pull("smakubi/modified-prompt")

from langchain_openai import ChatOpenAI
model = ChatOpenAI()

runnable = prompt | model

response = runnable.invoke({
	"profession": "biologist",
	"question": "What is special about parrots?",
})

print(response)