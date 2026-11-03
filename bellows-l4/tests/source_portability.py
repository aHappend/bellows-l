"""Inspect shipped source text without echoing private paths or secret values."""

from pathlib import Path
import re
import sys


def inspect_sources(root):
    issues = []
    host_path = re.compile(r"/(?:data|home|root|Users|mnt|tmp|private)/[^\s`\"']+")
    credential = re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|"
        r"AKIA[A-Z0-9]{16})\b|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    )
    for pattern in ("rtl/*.sv", "design/*.md", "tests/*.py",
                    "bellows_l3_reference/rtl/*.sv"):
        for path in sorted(root.glob(pattern)):
            for line_number, line in enumerate(path.read_text().splitlines(), 1):
                for expression, label in ((host_path, "private absolute host path"),
                                          (credential, "credential-like value")):
                    if expression.search(line):
                        issues.append({"file": path.relative_to(root).as_posix(),
                                       "line": line_number, "diagnostic": label})
    return issues


def main():
    root = Path(__file__).resolve().parents[1]
    issues = inspect_sources(root)
    for issue in issues:
        print(f"ASSERT PORTABILITY {issue['file']}:{issue['line']}: {issue['diagnostic']}")
    if issues:
        return 1
    print("SUMMARY SOURCE PORTABILITY no private host paths or recognized credentials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
