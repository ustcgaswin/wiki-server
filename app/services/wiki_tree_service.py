from uuid import UUID
import os
import json


IGNORE_DIRS = {
    # VCS, IDEs, caches, build outputs, etc.
    ".git", ".svn", ".hg",
    ".idea", ".vscode",
    "__pycache__", ".mypy_cache", ".pytest_cache",
    ".cache", "logs", "log",
    "tmp", "temp", "htmlcov",
    "env", "venv", ".venv",
    "node_modules",
    "build", "dist", "out",
    "target",                   # Maven/Gradle/Rust/Scala
    ".gradle", ".next", ".serverless", ".terraform",
    ".DS_Store",
    # Scala-specific
    ".metals", ".bloop", ".ivy2",
    "project",                  # sbt sub-project dir
    # Ruby, bundler, Vagrant, Jupyter, etc.
    ".bundle", ".vagrant",
    ".ipynb_checkpoints",
    # Eclipse
    ".metadata", ".settings",
    ".classpath", ".project",
}

code_extensions = [
    # existing
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c",
    ".h", ".hpp", ".go", ".rs", ".php", ".swift", ".cs",
    ".html", ".css",
    # scripts
    ".sh", ".bash", ".ps1",
    # notebooks
    ".ipynb",
    # added for Scala / SQL
    ".scala", ".sbt", ".sql",
    # other popular languages
    ".rb",      # Ruby
    ".kt", ".kts",  # Kotlin
    ".dart",    # Dart/Flutter
    ".r",       # R
    ".hs",      # Haskell
    ".clj", ".cljs",  # Clojure
    ".groovy",
    ".elm",
    ".vue",     # Vue single-file components
    ".lua",
    ".coffee",  # CoffeeScript
    ".m", ".mm",# Objective-C
    ".fs", ".fsi", ".fsx",  # F#
    ".erl",     # Erlang
    ".ex", ".exs", # Elixir
    ".asm", ".s", # Assembly
    ".config"
]

doc_extensions = [
    # existing
    ".md", ".txt", ".rst", ".json", ".yaml", ".yml",
    # config / markup
    ".ini", ".toml", ".xml", ".cfg", ".props", ".properties",
    # data / queries
    ".sql",       # SQL queries
    ".csv", ".tsv",
    ".config"
]

allowed_exts = set(code_extensions + doc_extensions)

IGNORE_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    ".DS_Store", ".env", ".gitignore",
    # caches, bytecode, debug
    "*.log", "*.pyc", "*.pyo", "*.class", "*.jar", "*.war", "*.ear",
    "npm-debug.log", "yarn-debug.log", "yarn-error.log",
    # archives
    "*.zip", "*.tar", "*.tar.gz", "*.rar", "*.7z",
    "*.db",
    # npm/Yarn config
    ".npmrc", ".yarnrc",
    # dotenv variants
    ".env.local", ".env.*",
    # linters / formatters
    ".eslintcache",
    # optional: if you don’t want to treat Makefiles as "code"
    "Makefile", "makefile",
}




def get_wiki_structure_for_project(project_id: UUID) -> dict:
    """
    Loads and returns the wiki tree structure from project_analysis/{project_id}/wiki_tree.json.
    Returns an empty dict if the file does not exist or is invalid.
    """
    wiki_tree_path = os.path.join("project_analysis", str(project_id), "wiki_tree.json")
    if os.path.exists(wiki_tree_path):
        try:
            with open(wiki_tree_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def create_wiki_structure(project_id: UUID) -> dict:
    """
    Scans the project_storage/{project_id} directory and builds a wiki tree structure.
    Only includes non-empty files with extensions listed in allowed_exts.
    Ignores irrelevant folders like .git, build, node_modules, dist, target, etc.
    Ignores files listed in IGNORE_FILES.
    Each file is a leaf node. Adds an 'overview' leaf node at the start.
    """
    root_dir = os.path.join("project_storage", str(project_id))

    def build_tree(current_path):
        tree = {}
        try:
            for entry in sorted(os.listdir(current_path)):
                full_path = os.path.join(current_path, entry)
                if os.path.isdir(full_path):
                    if entry in IGNORE_DIRS or entry.startswith('.'):
                        continue
                    subtree = build_tree(full_path)
                    if subtree:
                        tree[entry] = subtree
                else:
                    if entry in IGNORE_FILES:
                        continue
                    _, ext = os.path.splitext(entry)
                    if ext.lower() in allowed_exts:
                        try:
                            if os.path.getsize(full_path) > 0:
                                tree[entry] = {}
                        except Exception:
                            continue
        except Exception:
            pass
        return tree

    wiki_tree = {"overview": {}}
    if os.path.exists(root_dir):
        tree = build_tree(root_dir)
        wiki_tree.update(tree)
    return wiki_tree