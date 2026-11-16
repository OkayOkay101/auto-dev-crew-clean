from __future__ import annotations

import ast
from pathlib import Path


def _format_args(args: ast.arguments) -> str:
    parts: list[str] = []
    
    # Positional only
    for a in getattr(args, "posonlyargs", []):
        arg_str = a.arg
        if a.annotation:
            arg_str += f": {ast.unparse(a.annotation)}"
        parts.append(arg_str)
    if getattr(args, "posonlyargs", []):
        parts.append("/")

    # Positional / Keyword args with defaults
    total_args = len(args.args)
    defaults = args.defaults
    num_defaults = len(defaults)
    first_default_idx = total_args - num_defaults

    for i, a in enumerate(args.args):
        arg_str = a.arg
        if a.annotation:
            arg_str += f": {ast.unparse(a.annotation)}"
        if i >= first_default_idx:
            default_val = defaults[i - first_default_idx]
            arg_str += f" = {ast.unparse(default_val)}"
        parts.append(arg_str)

    # Vararg (*args)
    if args.vararg:
        varg = f"*{args.vararg.arg}"
        if args.vararg.annotation:
            varg += f": {ast.unparse(args.vararg.annotation)}"
        parts.append(varg)
    elif args.kwonlyargs:
        parts.append("*")

    # Kwonly args
    for a, default_val in zip(args.kwonlyargs, args.kw_defaults):
        arg_str = a.arg
        if a.annotation:
            arg_str += f": {ast.unparse(a.annotation)}"
        if default_val is not None:
            arg_str += f" = {ast.unparse(default_val)}"
        parts.append(arg_str)

    # Kwarg (**kwargs)
    if args.kwarg:
        kw = f"**{args.kwarg.arg}"
        if args.kwarg.annotation:
            kw += f": {ast.unparse(args.kwarg.annotation)}"
        parts.append(kw)

    return ", ".join(parts)


def extract_ast_skeleton(code: str, file_path: str = "") -> str:
    """Extracts classes, methods, signatures, docstrings from Python source, omitting implementation bodies."""
    try:
        tree = ast.parse(code)
    except Exception as e:
        return f"# Error parsing AST for {file_path}: {e}"

    lines: list[str] = []
    if file_path:
        lines.append(f"# File: {file_path}")

    # Top-level docstring
    module_doc = ast.get_docstring(tree, clean=True)
    if module_doc:
        first_line = module_doc.split("\n", 1)[0].strip()
        lines.append(f'"""{first_line}"""')

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            base_str = f"({', '.join(bases)})" if bases else ""
            lines.append(f"class {node.name}{base_str}:")
            
            class_doc = ast.get_docstring(node, clean=True)
            if class_doc:
                first_line = class_doc.split("\n", 1)[0].strip()
                lines.append(f'    """{first_line}"""')

            has_methods = False
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    has_methods = True
                    is_async = "async " if isinstance(item, ast.AsyncFunctionDef) else ""
                    args_str = _format_args(item.args)
                    ret_str = f" -> {ast.unparse(item.returns)}" if item.returns else ""
                    
                    fn_doc = ast.get_docstring(item, clean=True)
                    doc_line = ""
                    if fn_doc:
                        first_line = fn_doc.split("\n", 1)[0].strip()
                        doc_line = f' """{first_line}"""'
                    
                    lines.append(f"    {is_async}def {item.name}({args_str}){ret_str}: ...{doc_line}")
            
            if not has_methods and not class_doc:
                lines.append("    ...")
            lines.append("")

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_async = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            args_str = _format_args(node.args)
            ret_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            
            fn_doc = ast.get_docstring(node, clean=True)
            doc_line = ""
            if fn_doc:
                first_line = fn_doc.split("\n", 1)[0].strip()
                doc_line = f' """{first_line}"""'
                
            lines.append(f"{is_async}def {node.name}({args_str}){ret_str}: ...{doc_line}")

    return "\n".join(lines).strip()


def generate_repo_skeleton(
    repo_dir: Path,
    max_chars: int = 15000,
    exclude_dirs: tuple[str, ...] = (
        ".git", ".venv", "venv", "__pycache__", "tests", "node_modules",
        "dist", "build", ".pytest_cache", ".ruff_cache", "site-packages"
    )
) -> str:
    """Walks Python files in repo_dir and produces a consolidated skeleton summary."""
    if not repo_dir.exists() or not repo_dir.is_dir():
        return ""

    repo_dir = repo_dir.resolve()
    skeletons: list[str] = []
    current_chars = 0

    py_files = sorted(
        [
            f for f in repo_dir.rglob("*.py")
            if not any(part in exclude_dirs for part in f.relative_to(repo_dir).parts)
        ],
        key=lambda f: (len(f.parts), str(f))
    )

    for f in py_files:
        try:
            rel_path = f.relative_to(repo_dir).as_posix()
            code = f.read_text(encoding="utf-8", errors="ignore")
            file_skel = extract_ast_skeleton(code, file_path=rel_path)
            if file_skel.strip():
                if current_chars + len(file_skel) > max_chars:
                    skeletons.append("# ... (Remaining files truncated to keep prompt concise)")
                    break
                skeletons.append(file_skel)
                current_chars += len(file_skel) + 2
        except Exception:
            continue

    return "\n\n".join(skeletons)
