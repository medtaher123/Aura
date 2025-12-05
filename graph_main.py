#graph_main.py
from langgraph.graph import StateGraph
from nodes import create_agent_executor
from state_schema import MyStateSchema
from translate import detect_language, translate_to_english, translate_from_english


graph_builder = StateGraph(state_schema=MyStateSchema)

graph_builder.add_node("agent_executor", create_agent_executor())
graph_builder.set_entry_point("agent_executor")
graph_builder.set_finish_point("agent_executor")

app = graph_builder.compile()

def format_output(result):
    output = result.get("output", "") or result.get("message", "")
    intermediate = result.get("intermediate_steps", [])
    urls = []

    for step in intermediate:
        observation = step[1]
        # If intermediate step contains a message, append it to output
        if isinstance(observation, dict) and observation.get("message") and observation.get("message") not in output:
            output += "\n" + observation.get("message")
        if isinstance(observation, dict) and "images" in observation:
            for img in observation["images"]:
                url = img.get("thumbnail")
                if url and url.startswith("http"):
                    urls.append(url)

    if urls and "http" not in output:
        url_str = "\n".join(urls)
        output += f"\n\n📷 Image URLs:\n" + url_str

    return output


if __name__ == "__main__":
    print("🌍 Agent ready — ask your question (type 'exit' to quit)")

    while True:
        query = input("You: ")
        if query.lower() in ["exit", "quit", "q"]:
            break
        lang = detect_language(query)
        translated_input = translate_to_english(query)
        result = app.invoke({"input": translated_input})
        output = format_output(result)
        translated_output = translate_from_english(output, lang)
        print(f"✅ Response: {translated_output}")