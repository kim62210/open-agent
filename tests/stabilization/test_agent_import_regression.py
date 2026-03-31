from pathlib import Path
import py_compile


ROOT = Path(__file__).resolve().parents[2]


def test_core_agent_module_compiles_without_syntax_error():
    py_compile.compile(str(ROOT / "core" / "agent.py"), doraise=True)


def test_core_unified_tools_module_compiles_without_syntax_error():
    py_compile.compile(str(ROOT / "core" / "unified_tools.py"), doraise=True)
