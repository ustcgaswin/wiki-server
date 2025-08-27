from pathlib import Path

def fill_tree_with_content(tree, wiki_dir: Path, prefix=""):
    result = {}
    for key, value in tree.items():
        path = f"{prefix}/{key}" if prefix else key
        if isinstance(value, dict) and value:
            result[key] = fill_tree_with_content(value, wiki_dir, path)
        else:
            md_path = wiki_dir / f"{path}.md"
            if md_path.exists():
                with open(md_path, "r", encoding="utf-8") as f:
                    result[key] = f.read()
            else:
                result[key] = None
    return result