import sys


def _scan_todos_cli(argv: list[str]) -> int | None:
    """`--scan-todos <owner/repo>`: print [AI-TODO] hits and exit (never creates issues)."""
    if "--scan-todos" not in argv:
        return None
    i = argv.index("--scan-todos")
    if i + 1 >= len(argv):
        print("--scan-todos ต้องระบุ owner/repo", file=sys.stderr)
        return 2
    import yaml
    from . import runner, todo_scan
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    cfg = yaml.safe_load((runner.ROOT / "config.yaml").read_text(encoding="utf-8"))
    res = todo_scan.run_scan(argv[i + 1], cfg, create=False)
    for it in res["items"]:
        print(f"{it['path']}:{it['line']} {it['text']}")
    print(f"พบ {len(res['items'])} รายการ")
    return 0


_rc = _scan_todos_cli(sys.argv[1:])
if _rc is None:
    from .runner import main
    _rc = main()
sys.exit(_rc)
