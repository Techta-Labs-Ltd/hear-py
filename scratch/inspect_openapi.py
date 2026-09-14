import json

with open(r"C:\Users\USER\.gemini\antigravity-ide\brain\75e0a8e9-e317-491c-b736-46fe492d11c2\.system_generated\steps\3138\content.md", "r", encoding="utf-8") as f:
    text = f.read()

idx = text.find("{")
data = json.loads(text[idx:])
components = data.get("components", {}).get("schemas", {})

targets = [
    "/api/v1/alexa/listeners/register",
    "/api/v1/alexa/listeners/sync",
    "/api/v1/alexa/listeners/resolve",
    "/api/v1/webhooks/event",
]

for path in targets:
    print("=" * 70)
    print(path)
    print("=" * 70)
    endpoint = data["paths"].get(path, {}).get("post", {})
    print("Summary:", endpoint.get("summary"))
    
    # Request body
    rb = endpoint.get("requestBody", {})
    content = rb.get("content", {}).get("application/json", {})
    schema_ref = content.get("schema", {})
    ref_name = schema_ref.get("$ref", "").split("/")[-1]
    print("Request Model Ref:", ref_name)
    if ref_name and ref_name in components:
        print("Request Model Properties:")
        print(json.dumps(components[ref_name].get("properties", {}), indent=2))
        print("Required:", components[ref_name].get("required", []))
        
    # Responses
    print("\nResponses:")
    for code, resp in endpoint.get("responses", {}).items():
        resp_schema = resp.get("content", {}).get("application/json", {}).get("schema", {})
        resp_ref = resp_schema.get("$ref", "").split("/")[-1]
        desc = resp.get("description")
        print(f"  [{code}] description: {desc}, ref: {resp_ref}")
        if resp_ref and resp_ref in components:
            print(f"  Response Model [{resp_ref}] Properties:")
            print(json.dumps(components[resp_ref].get("properties", {}), indent=2))
