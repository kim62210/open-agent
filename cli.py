import click
from rich.console import Console

from open_agent import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="open-agent")
def main():
    """Open Agent — AI Agent Platform with MCP Integration"""
    pass


@main.command()
@click.option("--host", default="127.0.0.1", help="바인딩 호스트 (기본: 127.0.0.1)")
@click.option("--port", default=4821, type=int, help="포트 번호 (기본: 4821)")
@click.option("--dev", is_flag=True, help="개발 모드 (CORS 허용, 리로드)")
@click.option("--expose", is_flag=True, help="외부 접속 허용 (0.0.0.0 바인딩, 보안 경고 표시)")
def start(host: str, port: int, dev: bool, expose: bool):
    """서버 시작 (프론트엔드 + API)"""
    import os
    import uvicorn

    if dev:
        os.environ["OPEN_AGENT_DEV"] = "1"

    if expose:
        host = "0.0.0.0"
        os.environ["OPEN_AGENT_EXPOSE"] = "1"
        os.environ["OPEN_AGENT_PORT"] = str(port)
        console.print("[bold yellow]⚠ 경고: 외부 접속이 허용됩니다 (0.0.0.0 바인딩).[/]")
        console.print("[yellow]  인증 없이 네트워크의 모든 기기에서 API에 접근할 수 있습니다.[/]")

    console.print(f"[bold green]Open Agent v{__version__}[/] starting on http://{host}:{port}")
    if dev:
        console.print("[dim]개발 모드: CORS 허용, 리로드 활성화[/]")

    uvicorn.run(
        "open_agent.server:app",
        host=host,
        port=port,
        reload=dev,
    )


@main.command()
def init():
    """~/.open-agent/ 초기 설정 파일 생성"""
    from open_agent.config import init_data_dir

    data_dir = init_data_dir()
    console.print(f"[green]✓[/] 데이터 디렉토리: {data_dir}")
    console.print("[dim]  .env, mcp.json, settings.json, skills.json, pages.json 생성 완료[/]")
    console.print(f"\n[bold]다음 단계:[/] {data_dir / '.env'} 에 사용할 프로바이더의 API 키를 설정하세요.\n")
    console.print("  [bold]GOOGLE_API_KEY[/]      — Google Gemini")
    console.print("  [bold]OPENAI_API_KEY[/]      — OpenAI GPT")
    console.print("  [bold]ANTHROPIC_API_KEY[/]   — Anthropic Claude")
    console.print("  [bold]XAI_API_KEY[/]         — xAI Grok")
    console.print("  [bold]OPENROUTER_API_KEY[/]  — OpenRouter (GLM, Kimi, Minimax 등)")
    console.print("\n[dim]  사용할 프로바이더의 키만 입력하면 됩니다.[/]")


@main.command()
def config():
    """현재 설정 경로 및 상태 표시"""
    from open_agent.config import get_data_dir

    data_dir = get_data_dir()
    console.print(f"[bold]데이터 디렉토리:[/] {data_dir}")

    for name in ["settings.json", "mcp.json", "skills.json", "pages.json", ".env"]:
        path = data_dir / name
        status = "[green]✓[/]" if path.exists() else "[red]✗[/]"
        console.print(f"  {status} {name}")


@main.command()
@click.argument("version", required=False)
def update(version: str | None):
    """최신 버전으로 업데이트 (GitHub Release 기반)

    VERSION을 지정하면 해당 태그로, 생략하면 최신 릴리스로 업데이트합니다.
    gh CLI가 설치되어 있으면 gh로, 없으면 GitHub API + urllib로 다운로드합니다.
    """
    import json
    import os
    import platform
    import subprocess
    import tempfile
    import urllib.request

    repo = "EJCHO-salary/track_platform"

    # --- 현재 플랫폼에 맞는 wheel 패턴 결정 ---
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin" and machine == "arm64":
        whl_suffix = "macosx_11_0_arm64.whl"
    elif system == "darwin":
        whl_suffix = "macosx_10_12_x86_64.whl"
    elif system == "windows":
        whl_suffix = "win_amd64.whl"
    else:
        whl_suffix = "manylinux"  # partial match

    # --- GitHub 토큰 확보 ---
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    has_gh = False
    if not token:
        try:
            result = subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=True,
            )
            token = result.stdout.strip()
            has_gh = True
        except Exception:
            pass
    else:
        # gh CLI 존재 여부 확인
        try:
            subprocess.run(["gh", "--version"], capture_output=True, check=True)
            has_gh = True
        except Exception:
            pass

    if not token:
        console.print(
            "[red]GitHub 토큰이 필요합니다.[/]\n"
            "  [dim]GITHUB_TOKEN 환경변수를 설정하거나 'gh auth login'을 실행하세요.[/]"
        )
        return

    try:
        # --- 릴리스 정보 조회 ---
        if version:
            tag = version if version.startswith("v") else f"v{version}"
        else:
            tag = None  # latest

        if has_gh:
            # gh CLI로 릴리스 정보 조회
            if tag:
                gh_cmd = ["gh", "release", "view", tag, "--repo", repo, "--json", "tagName,assets"]
                result = subprocess.run(gh_cmd, capture_output=True, text=True, check=True)
                release = json.loads(result.stdout)
                tag_name = release["tagName"]
            else:
                # latest 대신 릴리스 목록에서 v* 태그만 필터 (desktop-v*, mac-desktop-v* 제외)
                result = subprocess.run(
                    ["gh", "release", "list", "--repo", repo, "--limit", "20", "--json", "tagName"],
                    capture_output=True, text=True, check=True,
                )
                releases = json.loads(result.stdout)
                tag_name = None
                for rel in releases:
                    t = rel["tagName"]
                    if t.startswith("v") and not t.startswith(("desktop-v", "mac-desktop-v")):
                        tag_name = t
                        break
                if not tag_name:
                    console.print("[red]Python 패키지 릴리스(v*)를 찾을 수 없습니다.[/]")
                    return
                result = subprocess.run(
                    ["gh", "release", "view", tag_name, "--repo", repo, "--json", "tagName,assets"],
                    capture_output=True, text=True, check=True,
                )
                release = json.loads(result.stdout)
        else:
            # urllib로 GitHub API 직접 호출
            api_base = f"https://api.github.com/repos/{repo}/releases"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
            }
            if tag:
                api_url = f"{api_base}/tags/{tag}"
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req) as resp:
                    release = json.loads(resp.read())
                tag_name = release["tag_name"]
            else:
                # latest 대신 릴리스 목록에서 v* 태그만 필터
                api_url = f"{api_base}?per_page=20"
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req) as resp:
                    releases = json.loads(resp.read())
                tag_name = None
                release = None
                for rel in releases:
                    t = rel.get("tag_name", "")
                    if t.startswith("v") and not t.startswith(("desktop-v", "mac-desktop-v")):
                        tag_name = t
                        release = rel
                        break
                if not tag_name or not release:
                    console.print("[red]Python 패키지 릴리스(v*)를 찾을 수 없습니다.[/]")
                    return

        console.print(f"[bold]릴리스 {tag_name} 발견[/]")

        # --- 현재 플랫폼에 맞는 .whl 파일 찾기 ---
        assets = release.get("assets", [])
        whl_name = None
        all_whls = []
        for asset in assets:
            name = asset.get("name", "")
            if name.endswith(".whl"):
                all_whls.append(name)
                if whl_suffix in name:
                    whl_name = name

        if not whl_name and all_whls:
            # 플랫폼 매칭 실패 시 첫 번째 whl 사용 (pure python 등)
            whl_name = all_whls[0]
            console.print(f"[yellow]현재 플랫폼({system}/{machine})에 맞는 wheel이 없어 {whl_name}을 사용합니다.[/]")

        if not whl_name:
            console.print("[red]릴리스에 .whl 파일이 없습니다.[/]")
            return

        console.print(f"[dim]플랫폼: {system}/{machine} → {whl_name}[/]")

        # --- 임시 디렉토리에 다운로드 ---
        with tempfile.TemporaryDirectory() as tmpdir:
            local_whl = os.path.join(tmpdir, whl_name)

            if has_gh:
                # gh release download로 인증된 다운로드 (현재 플랫폼 wheel만)
                subprocess.run(
                    [
                        "gh", "release", "download", tag_name,
                        "--repo", repo,
                        "--pattern", whl_name,
                        "--dir", tmpdir,
                    ],
                    check=True,
                )
            else:
                # urllib로 직접 다운로드 (API URL + Accept header)
                asset_url = next(
                    a["url"] for a in release["assets"] if a["name"] == whl_name
                )
                dl_req = urllib.request.Request(asset_url, headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/octet-stream",
                })
                with urllib.request.urlopen(dl_req) as resp:
                    with open(local_whl, "wb") as f:
                        f.write(resp.read())

            # --- 로컬 .whl 파일로 설치 ---
            subprocess.run(
                ["uv", "tool", "install", "--force", "--python", "3.13", local_whl],
                check=True,
            )

        console.print(f"[green]✓ {tag_name} 업데이트 완료[/]")

    except urllib.error.HTTPError as e:
        if e.code == 404:
            console.print("[red]릴리스를 찾을 수 없습니다.[/]")
        else:
            console.print(f"[red]GitHub API 오류: {e.code} {e.reason}[/]")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        console.print(
            f"[red]명령 실행 실패[/]\n"
            f"[dim]{stderr[:300]}[/]"
        )
    except Exception as e:
        console.print(f"[red]업데이트 실패: {e}[/]")
