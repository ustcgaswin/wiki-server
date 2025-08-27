from pathlib import Path
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.agents.wiki_content_generation_agent import create_wiki_content_generation_agent


import logging
import tiktoken
logger = logging.getLogger(__name__)



MAX_AGENT_TOKENS = 100_000 

MAX_WORKER_AGENTS = 8  # Limit for parallel agent workers

def _write_dummy_markdown(file_path: Path, title: str):
    content = f"# {title}\n\nThis is dummy content for **{title}**."
    file_path.write_text(content, encoding="utf-8")

def _generate_markdown_recursive(base_dir: Path, tree: dict):
    for node, children in tree.items():
        if isinstance(children, dict) and children:
            node_dir = base_dir / node
            node_dir.mkdir(parents=True, exist_ok=True)
            _generate_markdown_recursive(node_dir, children)
        else:
            md_file = base_dir / f"{node}.md"
            _write_dummy_markdown(md_file, node)

def generate_wiki_for_project_alternate(project_id: UUID, tree: dict):
    wiki_dir = Path("project_wiki") / str(project_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)
    _generate_markdown_recursive(wiki_dir, tree)

def _collect_leaf_nodes(tree, rel_path=Path()):
    leaves = []
    for node, children in tree.items():
        if isinstance(children, dict) and children:
            leaves.extend(_collect_leaf_nodes(children, rel_path / node))
        else:
            leaves.append((rel_path, node))
    return leaves

def generate_wiki_for_project(project_id: UUID, tree: dict):
    """
    Generates markdown files for each leaf node in the wiki tree structure
    under project_wiki/{project_id}, using a separate agent for each file.
    Processes files in parallel up to MAX_WORKER_AGENTS.
    """
    storage_dir = Path("project_storage") / str(project_id)
    wiki_dir = Path("project_wiki") / str(project_id)
    wiki_dir.mkdir(parents=True, exist_ok=True)

    leaf_nodes = _collect_leaf_nodes(tree)

    def process_leaf(args):
        rel_path, node = args
        try:
            source_file = storage_dir / rel_path / node
            file_content = ""
            if source_file.exists():
                file_content = source_file.read_text(encoding="utf-8")
                tokenizer = tiktoken.get_encoding("cl100k_base")
                tokens = tokenizer.encode(file_content)
                token_count = len(tokens)
                if token_count > MAX_AGENT_TOKENS:
                    logger.warning(f"File '{source_file}' exceeds token limit: {token_count} tokens (limit: {MAX_AGENT_TOKENS})")
                    file_content = tokenizer.decode(tokens[:MAX_AGENT_TOKENS])
            agent = create_wiki_content_generation_agent()
            markdown = agent(page_title=node, file_content=file_content, wiki_tree=tree).content
            md_file = wiki_dir / rel_path / f"{node}.md"
            md_file.parent.mkdir(parents=True, exist_ok=True)
            md_file.write_text(markdown, encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to generate wiki for {node}: {e}", exc_info=True)


    with ThreadPoolExecutor(max_workers=MAX_WORKER_AGENTS) as executor:
        futures = [executor.submit(process_leaf, args) for args in leaf_nodes]
        for future in as_completed(futures):
            future.result()