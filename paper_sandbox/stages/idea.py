from paper_sandbox.ai_client import AIClient


def deepen_idea(cfg, idea, protocol=None, client=None):
    client = client or AIClient(cfg.deepseek_api_key, cfg.deepseek_base_url)
    prompt_parts = [
        "You are an academic collaborator. Help deepen the following research idea "
        "through dialogue. Ask 3 clarifying questions and propose 2 concrete angles.",
    ]
    if protocol:
        prompt_parts.append(f"Research protocol / plan:\n{protocol}\n")
    prompt_parts.append(f"Idea: {idea}")
    prompt = "\n\n".join(prompt_parts)
    return client.chat(prompt)
