import yaml

def load_rules_yaml(yaml_path="business_rules.yaml"):
    with open(yaml_path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
    # Flatten as markdown
    buf = []
    for rule in y['rules']:
        buf.append(f"### {rule['name']}\n{rule['description']}\n")
    return "\n".join(buf)