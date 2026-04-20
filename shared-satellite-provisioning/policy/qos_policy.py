import yaml


def load_runtime(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
