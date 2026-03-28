import asyncio
import json
import logging
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape, quoteattr as xml_quoteattr

import yaml

from open_agent.models.skill import SkillInfo, SkillDetail

logger = logging.getLogger(__name__)

# Frontmatter key order: name/description first, then version/dates, then rest
_FM_KEY_ORDER = ["name", "description", "version", "created_at", "updated_at"]


def _ordered_frontmatter(fm: Dict[str, Any]) -> Dict[str, Any]:
    """Return frontmatter dict with name/description at top."""
    ordered: Dict[str, Any] = {}
    for key in _FM_KEY_ORDER:
        if key in fm:
            ordered[key] = fm[key]
    for key, val in fm.items():
        if key not in ordered:
            ordered[key] = val
    return ordered


SKILL_TOOL_NAMES = {
    "read_skill", "run_skill_script", "read_skill_reference",
    "create_skill", "add_skill_script", "edit_skill_script",
    "patch_skill_script", "update_skill",
}

_WORKFLOW_EXCLUDE: set[str] = set()  # skill-creator도 라우팅 대상에 포함


class SkillManager:
    def __init__(self):
        self._skills: Dict[str, SkillInfo] = {}
        self._config_path: Optional[Path] = None
        self._disabled: set[str] = set()
        self._base_dirs: List[Path] = []
        self._bundled_dir: Optional[Path] = None
        self._workflow_bodies: Dict[str, str] = {}            # skill_name -> SKILL.md body

    def set_bundled_dir(self, path: str) -> None:
        self._bundled_dir = Path(path).resolve()

    # --- Config persistence ---

    def load_config(self, config_path: str) -> None:
        path = Path(config_path)
        if not path.is_absolute():
            from open_agent.config import get_config_path
            path = get_config_path(config_path)
        self._config_path = path

        if not path.exists():
            logger.info(f"Skills config not found: {path}, starting fresh")
            self._disabled = set()
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._disabled = set(data.get("disabled", []))
            logger.info(f"Loaded skills config from {path} ({len(self._disabled)} disabled)")
        except Exception as e:
            logger.warning(f"Failed to load skills config: {e}")
            self._disabled = set()

    def _save_config(self) -> None:
        if not self._config_path:
            return
        data = {"disabled": sorted(self._disabled)}
        self._config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # --- Discovery ---

    def _parse_frontmatter(self, skill_md_path: Path) -> Dict[str, Any]:
        content = skill_md_path.read_text(encoding="utf-8")
        if not content.startswith("---"):
            raise ValueError(f"No YAML frontmatter: {skill_md_path}")
        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError(f"Invalid frontmatter format: {skill_md_path}")
        return yaml.safe_load(parts[1]) or {}

    _SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv"}
    _SKIP_FILES = {"__init__.py"}

    def _list_dir_files(self, base: Path, subdirs: List[str], extensions: Tuple[str, ...]) -> List[str]:
        """여러 대안 디렉토리명을 탐색하고 하위 디렉토리까지 재귀 검색"""
        for subdir in subdirs:
            d = base / subdir
            if d.is_dir():
                return sorted(
                    str(f.relative_to(d)).replace("\\", "/")
                    for f in d.rglob("*")
                    if f.is_file()
                    and f.suffix in extensions
                    and f.name not in self._SKIP_FILES
                    and not f.name.startswith("_")
                    and not any(p in self._SKIP_DIRS for p in f.relative_to(d).parts)
                )
        return []

    def discover_skills(self, dirs: List[str]) -> None:
        self._base_dirs = []

        for d in dirs:
            p = Path(d)
            if not p.is_absolute():
                from open_agent.config import get_skills_dir
                p = get_skills_dir()
            self._base_dirs.append(p)

        discovered: Dict[str, SkillInfo] = {}
        for base_dir in self._base_dirs:
            if not base_dir.is_dir():
                logger.info(f"Skills directory not found: {base_dir}, skipping")
                continue

            for skill_dir in sorted(base_dir.iterdir()):
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.is_file():
                    continue

                try:
                    fm = self._parse_frontmatter(skill_md)
                    name = fm.get("name", skill_dir.name)

                    if name in discovered:
                        continue  # 먼저 발견된 스킬(사용자 디렉토리)이 우선

                    scripts = self._list_dir_files(skill_dir, ["scripts", "templates"], (".py", ".sh", ".js"))
                    references = self._list_dir_files(skill_dir, ["references", "reference"], (".md", ".txt", ".json", ".yaml", ".yml"))

                    # allowed-tools: 리스트 또는 comma-separated 문자열 지원
                    raw_tools = fm.get("allowed-tools", [])
                    if isinstance(raw_tools, str):
                        allowed_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
                    elif isinstance(raw_tools, list):
                        allowed_tools = [str(t).strip() for t in raw_tools if str(t).strip()]
                    else:
                        allowed_tools = []

                    is_bundled = bool(self._bundled_dir and skill_dir.resolve().is_relative_to(self._bundled_dir))

                    discovered[name] = SkillInfo(
                        name=name,
                        description=fm.get("description", ""),
                        path=str(skill_dir.resolve()),
                        scripts=scripts,
                        references=references,
                        enabled=name not in self._disabled,
                        license=fm.get("license"),
                        compatibility=fm.get("compatibility"),
                        metadata=fm.get("metadata"),
                        allowed_tools=allowed_tools,
                        is_bundled=is_bundled,
                        version=fm.get("version", "1.0.0"),
                        created_at=fm.get("created_at"),
                        updated_at=fm.get("updated_at"),
                    )
                    logger.info(f"Discovered skill: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load skill ({skill_dir}): {e}")

        self._skills = discovered
        logger.info(f"Total skills discovered: {len(self._skills)}")

        # 번들 워크플로우 스킬 캐시 + 라우터 업데이트
        self._workflow_bodies.clear()
        summaries: Dict[str, str] = {}
        for name, skill in self._skills.items():
            if not skill.is_bundled or name in _WORKFLOW_EXCLUDE:
                continue
            # description 첫 문장을 라우터용 요약으로 사용
            desc = skill.description or ""
            first_sentence = desc.split("\n")[0].split("。")[0].split(". ")[0].strip()
            if first_sentence:
                summaries[name] = first_sentence
            skill_md = Path(skill.path) / "SKILL.md"
            if skill_md.is_file():
                content = skill_md.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    self._workflow_bodies[name] = parts[2].strip() if len(parts) >= 3 else ""
                else:
                    self._workflow_bodies[name] = content.strip()

        # LLM 라우터에 스킬 요약 전달
        from open_agent.core.workflow_router import workflow_router
        workflow_router.update_skills(summaries)
        logger.info(f"Workflow skills cached: {len(summaries)} skills (LLM routing)")

    # --- CRUD ---

    def get_all_skills(self) -> List[SkillInfo]:
        return list(self._skills.values())

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        return self._skills.get(name)

    def load_skill_content(self, name: str) -> Optional[SkillDetail]:
        skill = self._skills.get(name)
        if not skill:
            return None
        skill_md = Path(skill.path) / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
        return SkillDetail(**skill.model_dump(), content=content)

    def _resolve_subdir(self, skill_base: Path, candidates: List[str], rel_path: str) -> Optional[Path]:
        """대안 디렉토리 후보 중 파일이 존재하는 경로를 반환 (path traversal 검증 포함)"""
        for subdir in candidates:
            full_path = (skill_base / subdir / rel_path).resolve()
            if not full_path.is_relative_to(skill_base):
                raise ValueError(f"Path traversal detected: {rel_path}")
            if full_path.is_file():
                return full_path
        return None

    def load_skill_reference(self, name: str, ref_path: str) -> Optional[str]:
        skill = self._skills.get(name)
        if not skill:
            return None

        skill_base = Path(skill.path).resolve()
        full_path = self._resolve_subdir(skill_base, ["references", "reference"], ref_path)
        if not full_path:
            return None
        return full_path.read_text(encoding="utf-8")

    async def execute_script(self, name: str, script: str, args: List[str] | None = None) -> Dict[str, Any]:
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "error": f"Skill not found: {name}"}

        skill_base = Path(skill.path).resolve()
        try:
            script_path = self._resolve_subdir(skill_base, ["scripts", "templates"], script)
        except ValueError as e:
            return {"success": False, "error": str(e)}
        if not script_path:
            return {"success": False, "error": f"Script not found: {script}"}

        # Determine runner based on extension
        import sys
        ext = script_path.suffix
        if ext == ".py":
            python_cmd = "python" if sys.platform == "win32" else "python3"
            cmd = [python_cmd, str(script_path)] + (args or [])
        elif ext == ".sh":
            bash = shutil.which("bash")
            if not bash:
                return {"success": False, "error": "bash not found. .sh scripts require bash (install Git Bash or WSL on Windows)."}
            cmd = [bash, str(script_path)] + (args or [])
        elif ext == ".js":
            cmd = ["node", str(script_path)] + (args or [])
        elif ext in (".bat", ".cmd", ".ps1"):
            if ext == ".ps1":
                cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script_path)] + (args or [])
            else:
                cmd = ["cmd", "/c", str(script_path)] + (args or [])
        else:
            return {"success": False, "error": f"Unsupported script type: {ext}"}

        try:
            from open_agent.core.workspace_tools import get_sanitized_env
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(skill_base),
                env=get_sanitized_env(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "returncode": proc.returncode,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"success": False, "error": "Script execution timed out (60s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_skill(self, name: str, description: str, instructions: str = "") -> SkillInfo:
        if not self._base_dirs:
            raise ValueError("No skill directories configured")

        skill_dir = self._base_dirs[0] / name
        skill_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        fm = {
            "name": name,
            "description": description,
            "version": "1.0.0",
            "created_at": now,
            "updated_at": now,
        }
        body = instructions if instructions else f"# {name}\n\nSkill instructions go here.\n"
        # Strip frontmatter from instructions if included
        if body.startswith("---"):
            body_parts = body.split("---", 2)
            if len(body_parts) >= 3:
                incoming_fm = yaml.safe_load(body_parts[1]) or {}
                for k, v in incoming_fm.items():
                    if k not in ("version", "created_at", "updated_at"):
                        fm[k] = v
                body = body_parts[2].lstrip("\n")
        frontmatter = "---\n" + yaml.dump(_ordered_frontmatter(fm), allow_unicode=True, default_flow_style=False, sort_keys=False) + "---\n"
        (skill_dir / "SKILL.md").write_text(frontmatter + "\n" + body, encoding="utf-8")

        self._rediscover()
        skill = self._skills.get(name)
        if not skill:
            raise ValueError(f"스킬 '{name}' 생성 후 로딩 실패 — SKILL.md 형식을 확인하세요.")
        return skill

    def import_from_path(self, source_path: str) -> SkillInfo:
        """기존 스킬 폴더를 skills 디렉토리로 복사하여 등록"""
        if not self._base_dirs:
            raise ValueError("No skill directories configured")

        src = Path(source_path).resolve()
        if not src.is_dir():
            raise ValueError(f"Source is not a directory: {source_path}")
        if not (src / "SKILL.md").is_file():
            raise ValueError(f"SKILL.md not found in: {source_path}")

        fm = self._parse_frontmatter(src / "SKILL.md")
        name = fm.get("name", src.name)

        dest = self._base_dirs[0] / name
        if dest.exists():
            raise ValueError(f"Skill '{name}' already exists")

        shutil.copytree(str(src), str(dest))
        self._rediscover()
        skill = self._skills.get(name)
        if not skill:
            raise ValueError(f"스킬 '{name}' 임포트 후 로딩 실패 — SKILL.md 형식을 확인하세요.")
        return skill

    def import_from_zip(self, zip_path: str) -> SkillInfo:
        """zip 파일을 풀어서 스킬로 등록"""
        if not self._base_dirs:
            raise ValueError("No skill directories configured")

        zp = Path(zip_path)
        if not zp.is_file():
            raise ValueError(f"Zip file not found: {zip_path}")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(str(zp), "r") as zf:
                # Zip Slip 방지: 각 엔트리 경로가 추출 대상 디렉토리 내부인지 검증
                tmp_resolved = Path(tmpdir).resolve()
                for entry in zf.namelist():
                    entry_path = (tmp_resolved / entry).resolve()
                    if not entry_path.is_relative_to(tmp_resolved):
                        raise ValueError(f"Zip Slip detected: {entry}")
                zf.extractall(tmpdir)

            # zip 내부 구조 탐색: SKILL.md를 가진 폴더 찾기
            tmp = Path(tmpdir)
            skill_root = self._find_skill_root(tmp)
            if not skill_root:
                raise ValueError("SKILL.md not found in zip archive")

            return self.import_from_path(str(skill_root))

    def import_from_zip_bytes(self, data: bytes, filename: str) -> SkillInfo:
        """업로드된 zip 바이트를 임시 저장 후 등록"""
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        try:
            return self.import_from_zip(tmp_path)
        finally:
            os.unlink(tmp_path)

    def _find_skill_root(self, base: Path) -> Optional[Path]:
        """디렉토리 트리에서 SKILL.md가 있는 최상위 폴더를 찾음"""
        if (base / "SKILL.md").is_file():
            return base
        for child in sorted(base.iterdir()):
            if child.is_dir() and not child.name.startswith("__"):
                if (child / "SKILL.md").is_file():
                    return child
        return None

    def _rediscover(self) -> None:
        self.discover_skills([str(d) for d in self._base_dirs])

    def delete_skill(self, name: str) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False

        if skill.is_bundled:
            raise ValueError(f"번들 스킬 '{name}'은(는) 삭제할 수 없습니다.")

        shutil.rmtree(skill.path, ignore_errors=True)
        self._skills.pop(name, None)
        self._disabled.discard(name)
        self._save_config()
        return True

    def toggle_skill(self, name: str, enabled: bool) -> Optional[SkillInfo]:
        skill = self._skills.get(name)
        if not skill:
            return None

        skill.enabled = enabled
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        self._save_config()
        return skill

    def update_skill(self, name: str, description: str | None = None, instructions: str | None = None, enabled: bool | None = None) -> Optional[SkillInfo]:
        skill = self._skills.get(name)
        if not skill:
            return None

        if skill.is_bundled and (description is not None or instructions is not None):
            raise ValueError(f"번들 스킬 '{name}'의 설명/지시사항은 수정할 수 없습니다.")

        if enabled is not None:
            self.toggle_skill(name, enabled)

        if description is not None or instructions is not None:
            skill_md_path = Path(skill.path) / "SKILL.md"
            content = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""

            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    fm = yaml.safe_load(parts[1]) or {}
                    if description is not None:
                        fm["description"] = description
                        skill.description = description
                    body = instructions if instructions is not None else parts[2].lstrip("\n")
                    # Strip frontmatter from instructions if included
                    if body.startswith("---"):
                        body_parts = body.split("---", 2)
                        if len(body_parts) >= 3:
                            # Merge frontmatter fields from instructions into fm
                            incoming_fm = yaml.safe_load(body_parts[1]) or {}
                            for k, v in incoming_fm.items():
                                if k == "description" and description is not None:
                                    continue  # explicit description takes priority
                                if k in ("version", "created_at", "updated_at"):
                                    continue  # version/date fields are auto-managed
                                fm[k] = v
                            if "description" in incoming_fm and description is None:
                                skill.description = incoming_fm["description"]
                            body = body_parts[2].lstrip("\n")
                    # Auto-bump patch version and update timestamp
                    cur_ver = fm.get("version", "1.0.0")
                    try:
                        major, minor, patch = cur_ver.split(".")
                        fm["version"] = f"{major}.{minor}.{int(patch) + 1}"
                    except (ValueError, AttributeError):
                        fm["version"] = "1.0.1"
                    fm["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if "created_at" not in fm:
                        fm["created_at"] = fm["updated_at"]
                    # Sync version/date to SkillInfo
                    skill.version = fm["version"]
                    skill.updated_at = fm["updated_at"]
                    skill.created_at = fm.get("created_at")
                    new_content = "---\n" + yaml.dump(_ordered_frontmatter(fm), allow_unicode=True, default_flow_style=False, sort_keys=False) + "---\n\n" + body
                    skill_md_path.write_text(new_content, encoding="utf-8")

        return skill

    # --- LLM Integration ---

    def generate_skills_xml(self) -> str:
        enabled = [s for s in self._skills.values() if s.enabled]
        if not enabled:
            return ""

        lines = ["<available_skills>"]
        for skill in enabled:
            parts = [f'  <skill name={xml_quoteattr(skill.name)}>']
            parts.append(f'    <description>{xml_escape(skill.description)}</description>')
            if skill.scripts:
                scripts_str = ", ".join(xml_escape(s) for s in skill.scripts)
                parts.append(f'    <scripts>{scripts_str}</scripts>')
            if skill.references:
                refs_str = ", ".join(xml_escape(r) for r in skill.references)
                parts.append(f'    <references>{refs_str}</references>')
            parts.append('  </skill>')
            lines.append("\n".join(parts))
        lines.append("</available_skills>")
        lines.append("스킬의 상세 지시사항은 read_skill로 확인하세요.")
        return "\n".join(lines)

    def get_workflow_body(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """워크플로우 body 반환 (라우터가 선택한 스킬에 대해)."""
        skill = self._skills.get(skill_name)
        if not skill or not skill.enabled:
            return None
        body = self._workflow_bodies.get(skill_name, "")
        if not body:
            return None
        return {
            "name": skill_name,
            "body": body,
            "scripts": skill.scripts,
            "references": skill.references,
        }

    def get_skill_tools(self) -> List[Dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "create_skill",
                    "description": (
                        "새로운 스킬을 생성하여 등록합니다. "
                        "name은 kebab-case(예: document-reader)로 지정하며, 이 이름이 스킬 디렉토리명이 됩니다. "
                        "instructions에는 SKILL.md 본문 전체를 작성하세요 — 사용 시기, 단계별 절차, 주의사항을 포함해야 합니다. "
                        "생성 후 실행 가능한 스크립트가 필요하면 add_skill_script로 별도 추가해야 합니다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "스킬 이름 (kebab-case, 예: document-reader). 스킬 디렉토리명으로 사용됨"},
                            "description": {"type": "string", "description": "스킬 설명 — 언제, 어떤 상황에서 사용하는지 한 줄로 요약"},
                            "instructions": {"type": "string", "description": "SKILL.md 본문 — 상세 지시사항, 단계별 절차, 예시, 주의사항 포함"},
                        },
                        "required": ["name", "description", "instructions"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "add_skill_script",
                    "description": (
                        "기존 스킬에 실행 가능한 스크립트 파일을 추가합니다. "
                        "지원 언어: Python(.py), Bash(.sh), Node.js(.js), PowerShell(.ps1), Batch(.bat/.cmd). "
                        "스크립트는 스킬의 scripts/ 디렉토리에 저장되며, 디렉토리가 없으면 자동 생성됩니다. "
                        "외부 파일을 인자로 받을 경우 절대 경로를 전제로 작성하세요. 표준 라이브러리만 사용하는 것을 권장합니다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "대상 스킬 이름 — 반드시 기존에 생성된 스킬이어야 함"},
                            "filename": {"type": "string", "description": "스크립트 파일명 (확장자 포함, 예: extract_pptx.py)"},
                            "content": {"type": "string", "description": "스크립트 소스 코드 전체"},
                        },
                        "required": ["skill_name", "filename", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_skill_script",
                    "description": (
                        "스킬 스크립트 파일의 특정 부분을 찾아 교체합니다 (전체 덮어쓰기 대신 부분 수정). "
                        "4단계 퍼지 매칭(정확→우측공백→양측공백→유니코드 정규화)을 사용하여 "
                        "들여쓰기·공백 차이가 있어도 정확히 찾아냅니다. "
                        "매칭 실패 시 가장 유사한 영역을 힌트로 알려줍니다. "
                        "전체 파일을 다시 쓸 필요 없이 변경할 부분만 지정하세요 — 토큰을 절약합니다."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "대상 스킬 이름"},
                            "filename": {"type": "string", "description": "수정할 스크립트 파일명 (확장자 포함)"},
                            "old_string": {"type": "string", "description": "교체할 기존 코드 (파일에서 찾을 텍스트)"},
                            "new_string": {"type": "string", "description": "새로 삽입할 코드"},
                            "replace_all": {"type": "boolean", "description": "true면 모든 일치를 교체, false면 첫 번째만 (기본: false)"},
                        },
                        "required": ["skill_name", "filename", "old_string", "new_string"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "patch_skill_script",
                    "description": (
                        "스킬 스크립트에 unified diff 패치를 적용합니다. "
                        "여러 위치를 한 번에 수정할 때 edit_skill_script보다 효율적입니다. "
                        "표준 unified diff 형식(--- a/file, +++ b/file, @@ hunk headers)을 사용하세요."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "대상 스킬 이름"},
                            "filename": {"type": "string", "description": "패치를 적용할 스크립트 파일명 (확장자 포함)"},
                            "patch": {"type": "string", "description": "unified diff 형식의 패치 텍스트"},
                        },
                        "required": ["skill_name", "filename", "patch"],
                    },
                },
            },
        ]

        enabled = [s for s in self._skills.values() if s.enabled]
        if not enabled:
            return tools

        tools.append({
            "type": "function",
            "function": {
                "name": "update_skill",
                "description": (
                    "기존 스킬의 설명이나 지시사항(SKILL.md 본문)을 수정합니다. "
                    "description과 instructions는 각각 독립적으로 생략 가능하며, 생략한 필드는 기존 값이 유지됩니다. "
                    "스킬의 이름(name)은 변경할 수 없습니다. 스크립트 수정은 edit_skill_script(부분 교체) 또는 patch_skill_script(diff 적용)를 사용하세요."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "수정할 스킬 이름 — available_skills에 있는 이름"},
                        "description": {"type": "string", "description": "새로운 스킬 설명 (생략 시 기존 유지)"},
                        "instructions": {"type": "string", "description": "새로운 SKILL.md 본문 전체 (생략 시 기존 유지, 부분 수정 불가)"},
                    },
                    "required": ["name"],
                },
            },
        })

        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "read_skill",
                    "description": (
                        "등록된 스킬의 전체 지시사항(SKILL.md)을 읽어 반환합니다. "
                        "스킬을 사용하기 전에 반드시 이 도구로 지시사항을 확인하세요 — 시스템 프롬프트의 스킬 목록은 이름과 설명만 포함합니다. "
                        "반환 내용: YAML frontmatter(메타데이터) + Markdown 본문(절차, 주의사항, 스크립트 사용법)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {
                                "type": "string",
                                "description": "읽을 스킬 이름 — available_skills에 있는 이름",
                            }
                        },
                        "required": ["skill_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_skill_script",
                    "description": (
                        "스킬에 포함된 스크립트를 실행하고 stdout/stderr를 반환합니다. "
                        "지원 확장자: .py, .sh, .js, .bat, .cmd, .ps1. 실행 타임아웃은 60초입니다. "
                        "스크립트의 작업 디렉토리(cwd)는 스킬 디렉토리이므로, 워크스페이스 파일을 참조할 때는 반드시 절대 경로를 args로 전달하세요. "
                        "run_skill_script 호출 전에 read_skill로 스크립트 사용법을 먼저 확인하는 것을 권장합니다. "
                        '예시: run_skill_script(skill_name="data-analyzer", script_name="analyze.py", args=["/Users/user/workspace/data.csv", "--format", "json"])'
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "스킬 이름"},
                            "script_name": {"type": "string", "description": "실행할 스크립트 파일명 (확장자 포함, 예: analyze.py)"},
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "스크립트에 전달할 인자 목록. 워크스페이스 파일은 절대 경로 사용 (예: /Users/.../file.pptx)",
                            },
                        },
                        "required": ["skill_name", "script_name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_skill_reference",
                    "description": (
                        "스킬의 참조 문서(references/ 디렉토리)를 읽어 반환합니다. "
                        "참조 문서는 스킬이 참고하는 API 가이드, 템플릿, 설정 예시 등입니다. "
                        "사용 가능한 참조 파일 목록은 available_skills의 <references> 태그에서 확인하세요. "
                        "지원 형식: .md, .txt, .json, .yaml, .yml."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "skill_name": {"type": "string", "description": "스킬 이름"},
                            "reference_path": {"type": "string", "description": "참조 파일의 상대 경로 (references/ 기준, 예: api-guide.md)"},
                        },
                        "required": ["skill_name", "reference_path"],
                    },
                },
            },
        ])
        return tools

    def _resolve_script_path(self, skill_name: str, filename: str) -> Tuple[Optional[str], Optional[Path]]:
        """스크립트 파일 경로를 검증하고 반환. (에러메시지, 경로) 튜플."""
        skill = self.get_skill(skill_name)
        if not skill:
            return (f"Error: 스킬 '{skill_name}' 을(를) 찾을 수 없습니다.", None)
        if "/" in filename or "\\" in filename or ".." in filename:
            return (f"Error: 파일명에 경로 구분자나 '..'를 포함할 수 없습니다: {filename}", None)
        skill_base = Path(skill.path).resolve()
        script_path = self._resolve_subdir(skill_base, ["scripts", "templates"], filename)
        if not script_path:
            return (f"Error: 스크립트 '{filename}'을(를) 스킬 '{skill_name}'에서 찾을 수 없습니다.", None)
        return (None, script_path)

    def _handle_edit_skill_script(self, args: Dict[str, Any]) -> str:
        """Rust 퍼지 매칭을 사용한 스킬 스크립트 부분 수정."""
        from open_agent.core.fuzzy import find_closest_match, fuzzy_find, fuzzy_replace

        skill = self.get_skill(args["skill_name"])
        if skill and skill.is_bundled:
            return f"Error: 번들 스킬 '{args['skill_name']}'의 스크립트는 수정할 수 없습니다."

        err, script_path = self._resolve_script_path(args["skill_name"], args["filename"])
        if err:
            return err

        old_string = args["old_string"]
        new_string = args["new_string"]
        replace_all = args.get("replace_all", False)

        if not old_string:
            return "Error: old_string은 비어 있을 수 없습니다."

        content = script_path.read_text(encoding="utf-8")

        # 4-pass fuzzy matching
        match_mode, pos, matched_len = fuzzy_find(content, old_string)

        if match_mode is None:
            line_count = len(content.splitlines())
            best_line, ratio, snippet = find_closest_match(content, old_string)
            msg = f"old_string을 '{args['filename']}'에서 찾을 수 없습니다 ({line_count}줄)."
            if ratio > 0.4:
                snippet_preview = snippet[:300]
                old_preview = old_string[:300]
                msg += (
                    f"\n가장 유사한 영역 (줄 {best_line}, 유사도 {ratio:.0%}):\n"
                    f"  기대: {old_preview!r}\n"
                    f"  발견: {snippet_preview!r}\n"
                    f"힌트: read_skill 또는 read_skill_reference로 정확한 내용을 먼저 확인하세요."
                )
            return f"Error: {msg}"

        if match_mode == "exact":
            count = content.count(old_string)
            if count > 1 and not replace_all:
                return (
                    f"Error: old_string이 '{args['filename']}'에서 {count}번 발견되었습니다. "
                    "replace_all=true로 모두 교체하거나, 더 고유한 문자열을 지정하세요."
                )
            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)
            replaced = count if replace_all else 1
        else:
            new_content = fuzzy_replace(content, old_string, new_string, match_mode)
            replaced = 1

        script_path.write_text(new_content, encoding="utf-8")
        msg = f"스크립트 '{args['filename']}' 수정 완료: {replaced}건 교체"
        if match_mode != "exact":
            msg += f" ({match_mode} 매칭)"
        return msg

    def _handle_patch_skill_script(self, args: Dict[str, Any]) -> str:
        """Rust 패치 엔진을 사용한 스킬 스크립트 unified diff 적용."""
        from open_agent.core.fuzzy import apply_patch_to_string

        skill = self.get_skill(args["skill_name"])
        if skill and skill.is_bundled:
            return f"Error: 번들 스킬 '{args['skill_name']}'의 스크립트는 수정할 수 없습니다."

        err, script_path = self._resolve_script_path(args["skill_name"], args["filename"])
        if err:
            return err

        content = script_path.read_text(encoding="utf-8")
        patch_text = args["patch"]

        success, message, new_content = apply_patch_to_string(content, patch_text)
        if not success:
            return f"Error: {message}"

        script_path.write_text(new_content, encoding="utf-8")
        return f"스크립트 '{args['filename']}' 패치 적용 완료. {message}"

    async def handle_tool_call(self, tool_name: str, args: Dict[str, Any]) -> str:
        if tool_name == "read_skill":
            detail = self.load_skill_content(args["skill_name"])
            if not detail:
                return f"Error: Skill '{args['skill_name']}' not found"
            return detail.content

        elif tool_name == "run_skill_script":
            result = await self.execute_script(
                args["skill_name"],
                args["script_name"],
                args.get("args"),
            )
            if result["success"]:
                output = result.get("stdout", "Script executed successfully")
                if result.get("stderr"):
                    output += f"\n[stderr]: {result['stderr']}"
                return output
            # 실패 시에도 stdout이 있으면 포함 (JSON 결과 등 구조화된 출력 보존)
            stdout = result.get("stdout", "")
            error = result.get("error", result.get("stderr", "Unknown error"))
            if stdout:
                return f"[Exit code: {result.get('returncode', -1)}]\n{stdout}\n[stderr]: {error}"
            return f"Error: {error}"

        elif tool_name == "read_skill_reference":
            content = self.load_skill_reference(args["skill_name"], args["reference_path"])
            if content is None:
                return f"Error: Reference '{args['reference_path']}' not found in skill '{args['skill_name']}'"
            return content

        elif tool_name == "create_skill":
            try:
                info = self.create_skill(args["name"], args["description"], args["instructions"])
                return f"스킬 '{info.name}' 생성 완료. 경로: {info.path}"
            except Exception as e:
                return f"Error: 스킬 생성 실패 — {e}"

        elif tool_name == "update_skill":
            try:
                result = self.update_skill(
                    args["name"],
                    description=args.get("description"),
                    instructions=args.get("instructions"),
                )
                if not result:
                    return f"Error: 스킬 '{args['name']}' 을(를) 찾을 수 없습니다."
                return f"스킬 '{result.name}' 수정 완료."
            except Exception as e:
                return f"Error: 스킬 수정 실패 — {e}"

        elif tool_name == "add_skill_script":
            skill = self.get_skill(args["skill_name"])
            if not skill:
                return f"Error: 스킬 '{args['skill_name']}' 을(를) 찾을 수 없습니다."
            if skill.is_bundled:
                return f"Error: 번들 스킬 '{args['skill_name']}'의 스크립트는 수정할 수 없습니다."
            filename = args["filename"]
            # 파일명 검증: 경로 구분자 및 상위 참조 차단
            if "/" in filename or "\\" in filename or ".." in filename:
                return f"Error: 파일명에 경로 구분자나 '..'를 포함할 수 없습니다: {filename}"
            # 확장자 화이트리스트
            allowed_extensions = {".py", ".sh", ".js", ".bat", ".cmd", ".ps1"}
            ext = Path(filename).suffix.lower()
            if ext not in allowed_extensions:
                return f"Error: 허용되지 않는 확장자입니다: {ext} (허용: {', '.join(sorted(allowed_extensions))})"
            scripts_dir = Path(skill.path) / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            script_path = (scripts_dir / filename).resolve()
            # 이중 검증: resolve 후 scripts_dir 내부인지 확인
            if not script_path.is_relative_to(scripts_dir.resolve()):
                return f"Error: 경로 순회가 감지되었습니다: {filename}"
            script_path.write_text(args["content"], encoding="utf-8")
            self._rediscover()
            return f"스크립트 '{filename}' 추가 완료. 경로: {script_path}"

        elif tool_name == "edit_skill_script":
            return self._handle_edit_skill_script(args)

        elif tool_name == "patch_skill_script":
            return self._handle_patch_skill_script(args)

        return f"Error: Unknown skill tool '{tool_name}'"


skill_manager = SkillManager()
