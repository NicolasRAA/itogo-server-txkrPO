"""Метрики исходного кода на Python.

Считает по каждому пакету и по проекту в целом:
  строки кода, строки с комментариями, области имён (пакеты и модули), типы (классы),
  методы и функции, поля (атрибуты классов).

Запуск из корня проекта:
    python tools/metrics.py app
    python tools/metrics.py app tests --json

Подсчёт опирается на модули ast и tokenize из стандартной библиотеки, поэтому внешние пакеты не нужны.
Скрипт работает на Python 3.8 и новее.
"""
from __future__ import annotations

import ast
import io
import json
import sys
import tokenize
from dataclasses import asdict, dataclass, fields
from pathlib import Path

DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass
class Metrics:
    files: int = 0          # файлы .py
    lines_total: int = 0    # все физические строки
    lines_blank: int = 0    # пустые строки
    lines_code: int = 0     # строки кода: не пустые и не состоящие только из комментария или docstring
    lines_comment: int = 0  # строки с комментариями: целиком комментарий, docstring и код с комментарием в конце
    packages: int = 0       # каталоги с __init__.py
    modules: int = 0        # файлы .py, кроме __init__.py
    classes: int = 0        # типы
    methods: int = 0        # функции внутри классов
    functions: int = 0      # функции вне классов, включая вложенные
    fields: int = 0         # атрибуты классов и атрибуты self, заданные в методах

    def add(self, other: "Metrics") -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))

    @property
    def lines_nonblank(self) -> int:
        return self.lines_total - self.lines_blank

    @property
    def subprograms(self) -> int:
        return self.methods + self.functions


def docstring_lines(tree: ast.AST) -> set[int]:
    """Номера строк, которые заняты docstring модуля, класса или функции."""
    result: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, *DEFS)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                result.update(range(first.lineno, first.end_lineno + 1))
    return result


def comment_rows(source: str, lines: list[str]) -> tuple[set[int], set[int]]:
    """Строки с комментарием (любым) и строки, где кроме комментария ничего нет."""
    any_comment, only_comment = set(), set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row = token.start[0]
            any_comment.add(row)
            if lines[row - 1].strip().startswith("#"):
                only_comment.add(row)
    return any_comment, only_comment


def count_fields(cls: ast.ClassDef) -> int:
    """Поля класса: переменные в теле класса и self.x = ... в методах. Служебные __имена__ не считаются."""
    names: set[str] = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, DEFS) and stmt.args.args and stmt.args.args[0].arg == "self":
            for node in ast.walk(stmt):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                        names.add(target.attr)
    return len([n for n in names if not (n.startswith("__") and n.endswith("__"))])


def analyze_file(path: Path) -> Metrics:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    in_docstring = docstring_lines(tree)
    any_comment, only_comment = comment_rows(source, lines)

    m = Metrics(files=1, lines_total=len(lines))
    for number, line in enumerate(lines, 1):
        if not line.strip():
            m.lines_blank += 1
            continue
        if number in in_docstring or number in only_comment:
            m.lines_comment += 1
        else:
            m.lines_code += 1
            if number in any_comment:
                m.lines_comment += 1  # код с комментарием в конце строки

    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    m.classes = len(classes)
    m.methods = sum(1 for c in classes for s in c.body if isinstance(s, DEFS))
    m.functions = sum(1 for n in ast.walk(tree) if isinstance(n, DEFS)) - m.methods
    m.fields = sum(count_fields(c) for c in classes)
    if path.name != "__init__.py":
        m.modules = 1
    return m


def group_of(path: Path, root: Path) -> str:
    """Группа для таблицы: каждый модуль приложения отдельно, остальное по верхнему каталогу."""
    parts = path.relative_to(root).parts
    if len(parts) == 1:
        return root.name
    if parts[0] == "modules":
        return f"modules/{parts[1]}" if len(parts) >= 3 else root.name
    return parts[0]


def collect(root: Path) -> dict[str, Metrics]:
    groups: dict[str, Metrics] = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        group = groups.setdefault(group_of(path, root), Metrics())
        group.add(analyze_file(path))
        if path.name == "__init__.py":
            group.packages += 1
    return groups


def total(groups: dict[str, Metrics]) -> Metrics:
    result = Metrics()
    for m in groups.values():
        result.add(m)
    return result


def print_table(title: str, groups: dict[str, Metrics]) -> None:
    head = ["Группа", "Файлов", "Строк", "Кода", "Коммент.", "Пакетов", "Модулей", "Типов", "Методов", "Функций", "Полей"]
    rows = [(name, m) for name, m in groups.items()] + [("ВСЕГО", total(groups))]
    print(f"\n{title}\n")
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for name, m in rows:
        values = [m.files, m.lines_total, m.lines_code, m.lines_comment, m.packages, m.modules, m.classes, m.methods, m.functions, m.fields]
        print(f"| {name} | " + " | ".join(map(str, values)) + " |")


def main(argv: list[str]) -> None:
    as_json = "--json" in argv
    roots = [Path(a) for a in argv if not a.startswith("--")] or [Path("app")]
    report = {}
    for root in roots:
        groups = collect(root)
        report[str(root)] = {"groups": {k: asdict(v) for k, v in groups.items()}, "total": asdict(total(groups))}
        if not as_json:
            print_table(f"Каталог {root}", groups)
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
