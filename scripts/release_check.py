#!/usr/bin/env python3
"""MRH 發佈檢查（唯讀）：推送前在本機跑，GitHub Actions 跑同一支。只回報、不修正。

用法（在 repo 根目錄）：
    python3 -B scripts/release_check.py                      # 檢查，列出每一項違規
    python3 -B scripts/release_check.py --write-plugin-lock  # 重新登記外掛資料夾（先調外掛版本）

檢查七項，只用標準函式庫：
1. 個人內容：進版控的檔不得有個人路徑（macOS、Linux、Windows 的使用者資料夾）、SSH 形式的 GitHub 位址、email。
   保留給文件用的網域與 noreply 位址不算。該留的命中逐筆登記在 scripts/release_check_allow.json
   （file、kind、sha256、reason；sha256 是命中字串的雜湊，登記檔不抄出原文）。用不到的登記算違規。
2. 外掛結構：兩份市集檔與兩份清單都在、JSON 合法、名稱一致、來源是 repo 內的相對路徑；
   repo 根目錄與外掛資料夾根目錄都沒有可攜格式的 plugin.json；Hook 檔與它呼叫的腳本存在。
3. 版本一致，分兩組：程式版本（pyproject.toml、plugin.py 的備用版本、README 徽章、最新的 v* 標籤）
   與外掛版本（兩份清單、Claude 市集檔、登記檔）。沒有 v* 標籤時只提示。
4. 外掛資料夾不得有寫死的使用者資料夾、這台的帳號名、符號連結。$HOME、~/ 這種執行時才展開的寫法不算。沒有例外。
5. 外掛資料夾凍結：整個資料夾（每個資料夾與檔案的相對路徑、是否可執行、內容雜湊）登記在 packaging/plugin-lock.json。
   看的是工作目錄，所以沒進版控的 .DS_Store 與空資料夾也算。
6. 授權：LICENSE 在；第三方授權快照與 runtime-lock.json、snapshot.json 記的雜湊一致。
7. 不該進版控的東西：.DS_Store、runtime/、dist/、資料庫檔、workspace-allowlist.local.json。

結束碼：0 通過；1 有違規或無法檢查。
"""
import argparse
import getpass
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = "plugins/mrh"
PLUGIN_NAME = "mrh"
MARKETPLACE_NAME = "model-routing-harness"
CLAUDE_MARKETPLACE = ".claude-plugin/marketplace.json"
CODEX_MARKETPLACE = ".agents/plugins/marketplace.json"
CLAUDE_MANIFEST = PLUGIN_DIR + "/.claude-plugin/plugin.json"
CODEX_MANIFEST = PLUGIN_DIR + "/.codex-plugin/plugin.json"
PORTABLE_MANIFESTS = ("plugin.json", PLUGIN_DIR + "/plugin.json")
CODEX_SOURCE = {"source": "local", "path": "./" + PLUGIN_DIR}
LOCK_FILE = "packaging/plugin-lock.json"
ALLOW_FILE = "scripts/release_check_allow.json"
RUNTIME_LOCK = "packaging/macos-arm64/runtime-lock.json"
LICENSE_SNAPSHOT = "packaging/macos-arm64/license-snapshot"
FALLBACK_VERSION_FILE = "src/mrh/infrastructure/plugin.py"

LOCK_GUIDE = ("要同時更新登記（python3 -B scripts/release_check.py --write-plugin-lock）、調外掛版本，"
              "並在變更說明寫「Codex 使用者要重新信任」")

# 使用者資料夾底下的第一段名稱。左邊界擋掉路徑中段的 /home/、/Users/（例如暫存資料夾裡名叫 home 的子資料夾）。
NAME = r"[A-Za-z0-9._-]*[A-Za-z0-9_-]"
EDGE = r"(?<![A-Za-z0-9._-])"
HOME_PATHS = (
    ("個人路徑（Windows）", re.compile(r"(?i)\b[a-z]:[\\/]+Users[\\/]+" + NAME)),
    ("個人路徑（macOS）", re.compile(EDGE + r"/Users/" + NAME)),
    ("個人路徑（Linux）", re.compile(EDGE + r"/home/" + NAME)),
)
PERSONAL = tuple(("home-path", label, pattern) for label, pattern in HOME_PATHS) + (
    ("ssh-github", "SSH 形式的 GitHub 位址", re.compile(r"git@github\.com:[^\s\"'`<>)]*")),
    ("email", "email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
)
KINDS = ("home-path", "ssh-github", "email")
DOC_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
DOC_EMAIL_SUFFIXES = (".example.com", ".example.org", ".example.net", ".invalid", ".test", ".localhost", ".example")
# 不拿來比對的帳號名：不指向任何人的（CI 的機器、系統帳號），以及本來就公開在清單與網址裡的 GitHub 擁有者名稱。
GENERIC_ACCOUNTS = ("root", "runner", "runneradmin", "user", "admin", "administrator", "hugo0904")

BADGE_VERSION = re.compile(r"img\.shields\.io/badge/version-([^-\s)]+)-")
FALLBACK_VERSION = re.compile(r'^[ \t]*version[ \t]*=[ \t]*"(\d+\.\d+\.\d+)"[ \t]*$', re.MULTILINE)
RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
HOOK_TARGET = re.compile(r"\$\{(?:CLAUDE_)?PLUGIN_ROOT\}/([^\s\"']+)")
DATABASE_FILE = re.compile(r"(?i)\.(?:db|sqlite3?)(?:-(?:wal|shm|journal))?$")


class CheckError(Exception):
    """檢查本身跑不了（不是 git repo、找不到 git）。"""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")
    except OSError as exc:
        raise CheckError(f"找不到 git：{exc}") from exc


def tracked(root: Path) -> dict[str, str]:
    """進版控的檔：{相對路徑: git 記的 mode}。"""
    result = git(root, "ls-files", "-s", "-z")
    if result.returncode:
        raise CheckError(f"無法列出進版控的檔（{root} 不是 git repo？）：{result.stderr.strip()}")
    files = {}
    for entry in filter(None, result.stdout.split("\0")):
        meta, _, name = entry.partition("\t")
        files[name] = meta.split()[0]
    return files


def release_tags(root: Path) -> list[str]:
    return git(root, "tag", "-l", "v*").stdout.split()


def load_json(root: Path, name: str):
    """(內容, 問題)。讀不到或不是合法 JSON 時內容是 None。"""
    try:
        return json.loads((root / name).read_text(encoding="utf-8")), None
    except OSError:
        return None, f"`{name}`：不存在或讀不到"
    except ValueError as exc:
        return None, f"`{name}`：不是合法的 JSON（{exc}）"


def string_values(data):
    """JSON 裡所有的字串值。"""
    if isinstance(data, dict):
        for value in data.values():
            yield from string_values(value)
    elif isinstance(data, list):
        for value in data:
            yield from string_values(value)
    elif isinstance(data, str):
        yield data


def read_lines(root: Path, name: str) -> list[str] | None:
    """檔案內容逐行；符號連結看它指向哪裡。二進位檔（含 NUL）與不在工作目錄的檔回 None；不是 UTF-8 的文字檔照樣掃。"""
    path = root / name
    if path.is_symlink():
        return [os.readlink(path)]
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    return raw.decode("utf-8", errors="replace").splitlines()


# ---- 1 個人內容 ----

def harmless_email(text: str) -> bool:
    local, _, domain = text.lower().rpartition("@")
    return domain in DOC_EMAIL_DOMAINS or domain.endswith(DOC_EMAIL_SUFFIXES) or local in ("noreply", "no-reply")


def personal_hits(line: str, patterns=PERSONAL):
    """(種類, 說明, 命中的字)；同一段文字只算一次。"""
    taken: list[tuple[int, int]] = []
    for kind, label, pattern in patterns:
        for m in pattern.finditer(line):
            if any(m.start() < end and start < m.end() for start, end in taken):
                continue
            if kind == "email" and harmless_email(m.group(0)):
                continue
            taken.append(m.span())
            yield kind, label, m.group(0)


def load_allow(root: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    """([(file, kind, sha256)], 例外清單本身的問題)。"""
    if not (root / ALLOW_FILE).is_file():
        return [], []
    data, problem = load_json(root, ALLOW_FILE)
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return [], [problem or f"`{ALLOW_FILE}`：最上層要有 entries 陣列"]
    keys, problems = [], []
    for index, entry in enumerate(entries, 1):
        if not (isinstance(entry, dict) and set(entry) == {"file", "kind", "sha256", "reason"}
                and all(isinstance(value, str) and value.strip() for value in entry.values())
                and entry["kind"] in KINDS and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            problems.append(f"`{ALLOW_FILE}` 第 {index} 筆：要有 file、kind（{'、'.join(KINDS)}）、"
                            "sha256（命中字串的雜湊，64 個小寫十六進位字元）、reason 四個非空字串，不能有別的欄位")
            continue
        key = (entry["file"], entry["kind"], entry["sha256"])
        if key in keys:
            problems.append(f"`{ALLOW_FILE}` 第 {index} 筆：重複（{entry['file']}：{entry['sha256'][:12]}…）")
        else:
            keys.append(key)
    return keys, problems


def check_personal(root: Path, files, allow) -> tuple[list[str], list[str], list[str]]:
    """(違規, 例外清單裡用不到的項目, 讀不成文字而沒掃的檔)。"""
    found, used, skipped = [], set(), []
    for name in sorted(files):
        lines = read_lines(root, name)
        if lines is None:
            skipped.append(name)
            continue
        for number, line in enumerate(lines, 1):
            for kind, label, text in personal_hits(line):
                key = (name, kind, sha256_text(text))
                if key in allow:
                    used.add(key)
                else:
                    found.append(f"`{name}:{number}`：{label}：{text}（要保留就登記 kind={kind}、sha256={key[2]}）")
    unused = [f"`{ALLOW_FILE}`：用不到的項目（{file} 已經沒有這筆 {kind} 命中：{digest[:12]}…），刪掉"
              for file, kind, digest in allow if (file, kind, digest) not in used]
    return found, unused, skipped


# ---- 2 外掛結構 ----

def marketplace_plugin(data, name: str) -> tuple[dict | None, list[str]]:
    """市集檔裡的 mrh 那一筆。"""
    if not isinstance(data, dict):
        return None, [f"`{name}`：最上層要是物件"]
    found = []
    if data.get("name") != MARKETPLACE_NAME:
        found.append(f"`{name}`：市集名要是 {MARKETPLACE_NAME}（現在是 {data.get('name')!r}）")
    plugins = data.get("plugins") if isinstance(data.get("plugins"), list) else []
    entries = [entry for entry in plugins if isinstance(entry, dict) and entry.get("name") == PLUGIN_NAME]
    if len(entries) != 1:
        found.append(f"`{name}`：plugins 裡名為 {PLUGIN_NAME} 的外掛要剛好一筆（現在 {len(entries)} 筆）")
    return (entries[0] if len(entries) == 1 else None), found


def check_structure(root: Path, files) -> list[str]:
    found = []
    docs = {}
    for name in (CLAUDE_MARKETPLACE, CODEX_MARKETPLACE, CLAUDE_MANIFEST, CODEX_MANIFEST):
        if name not in files:
            found.append(f"`{name}`：沒有進版控")
        docs[name], problem = load_json(root, name)
        if problem:
            found.append(problem)
    for name in PORTABLE_MANIFESTS:
        if name in files or (root / name).exists():
            found.append(f"`{name}`：不得有可攜格式的 plugin.json；有了它 Codex 會改讀這份，Hook 整個消失")

    sources = ((CLAUDE_MARKETPLACE, "./" + PLUGIN_DIR), (CODEX_MARKETPLACE, CODEX_SOURCE))
    for name, expected in sources:
        if docs[name] is None:
            continue
        entry, problems = marketplace_plugin(docs[name], name)
        found += problems
        if entry is not None and entry.get("source") != expected:
            found.append(f"`{name}`：{PLUGIN_NAME} 的 source 要是 {json.dumps(expected)}"
                         f"（現在是 {json.dumps(entry.get('source'), ensure_ascii=False)}）；"
                         "來源只能是 repo 內的相對路徑，不得用 url 加 ref")

    hook_files = []
    for name in (CLAUDE_MANIFEST, CODEX_MANIFEST):
        manifest = docs[name]
        if manifest is None:
            continue
        if not isinstance(manifest, dict):
            found.append(f"`{name}`：最上層要是物件")
            continue
        if manifest.get("name") != PLUGIN_NAME:
            found.append(f"`{name}`：name 要是 {PLUGIN_NAME}（現在是 {manifest.get('name')!r}）")
        hooks = manifest.get("hooks")
        if isinstance(hooks, str):
            hook_files.append((Path(PLUGIN_DIR) / hooks).as_posix())
        elif name == CODEX_MANIFEST:
            found.append(f"`{name}`：hooks 要是外掛資料夾裡 Hook 檔的相對路徑（Codex 不會自己找）")
        else:
            hook_files.append(PLUGIN_DIR + "/hooks/hooks.json")  # Claude 預設讀的位置
    for name in hook_files:
        doc, problem = load_json(root, name)
        if problem:
            found.append(problem + "（清單指到的 Hook 檔）")
            continue
        for target in sorted({target for text in string_values(doc) for target in HOOK_TARGET.findall(text)}):
            if not (root / PLUGIN_DIR / target).is_file():
                found.append(f"`{name}`：Hook 呼叫的 `{target}` 不在外掛資料夾裡")
    return found


# ---- 3 版本一致 ----

def program_versions(root: Path, files) -> tuple[dict[str, str], list[str]]:
    """程式版本的各個來源：({來源: 版本}, 讀不到的問題)。"""
    versions, found = {}, []
    try:
        versions["pyproject.toml"] = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        found.append(f"`pyproject.toml`：讀不到 project.version（{exc!r}）")
    try:
        fallback = FALLBACK_VERSION.findall((root / FALLBACK_VERSION_FILE).read_text(encoding="utf-8"))
    except OSError:
        fallback = []
    if len(fallback) == 1:
        versions[f"{FALLBACK_VERSION_FILE} 的備用版本"] = fallback[0]
    else:
        found.append(f"`{FALLBACK_VERSION_FILE}`：寫死的備用版本（單獨一行的 version = \"x.y.z\"）要剛好一處，現在找到 {len(fallback)} 處")
    for name in sorted(files):
        if "/" in name or not re.fullmatch(r"README.*\.md", name):
            continue
        for index, version in enumerate(BADGE_VERSION.findall("\n".join(read_lines(root, name) or [])), 1):
            versions[f"{name} 的徽章" + (f"（第 {index} 個）" if index > 1 else "")] = version
    return versions, found


def plugin_versions(root: Path) -> dict[str, object]:
    """外掛版本的各個來源；讀不到的來源值是 None。"""
    versions = {}
    for name in (CLAUDE_MANIFEST, CODEX_MANIFEST):
        doc, _ = load_json(root, name)
        versions[name] = doc.get("version") if isinstance(doc, dict) else None
    doc, _ = load_json(root, CLAUDE_MARKETPLACE)
    entry, _ = marketplace_plugin(doc, CLAUDE_MARKETPLACE)
    versions[f"{CLAUDE_MARKETPLACE} 的 {PLUGIN_NAME}"] = entry.get("version") if entry else None
    doc, _ = load_json(root, LOCK_FILE)
    versions[LOCK_FILE] = doc.get("version") if isinstance(doc, dict) else None
    return versions


def check_versions(root: Path, files, tags) -> tuple[list[str], list[str]]:
    """(違規, 提示)。"""
    program, found = program_versions(root, files)
    notes = []
    base = program.get("pyproject.toml")
    if base is not None:
        found += [f"程式版本不一致：{source} 是 {version}，pyproject.toml 是 {base}"
                  for source, version in program.items() if version != base]
        releases = [tag for tag in tags if RELEASE_TAG.fullmatch(tag)]
        if not releases:
            notes.append(f"還沒有 v* 發行標籤，程式版本 {base} 沒有標籤可比（CI 要抓得到標籤才比得出來）")
        else:
            latest = max(releases, key=lambda tag: tuple(map(int, RELEASE_TAG.fullmatch(tag).groups())))
            if latest != "v" + base:
                found.append(f"程式版本不一致：最新的發行標籤是 {latest}，pyproject.toml 是 {base}")
    plugin = plugin_versions(root)
    if len(set(plugin.values())) != 1 or not isinstance(next(iter(plugin.values())), str):
        found.append("外掛版本不一致或缺漏：" + "、".join(f"{source} 是 {json.dumps(version)}" for source, version in plugin.items()))
    return found, notes


# ---- 4 外掛資料夾的靜態內容 ----

def local_account() -> str | None:
    """這台的帳號名；太短、不指向任何人、或等於公開的擁有者名稱時不比對。"""
    try:
        name = getpass.getuser().strip()
    except (OSError, KeyError, ImportError):
        return None
    return name if len(name) >= 3 and name.lower() not in GENERIC_ACCOUNTS else None


def walk_plugin(root: Path):
    """外掛資料夾底下的每一項：(相對於外掛資料夾的 POSIX 路徑, 完整路徑)，不跟著符號連結走。"""
    base = root / PLUGIN_DIR
    for current, dirs, names in os.walk(base, followlinks=False):
        for name in dirs + names:
            path = Path(current) / name
            yield path.relative_to(base).as_posix(), path


def check_plugin_static(root: Path, account: str | None) -> list[str]:
    found = []
    word = re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(account) + r"(?![A-Za-z0-9])") if account else None
    for relative, path in sorted(walk_plugin(root)):
        name = f"{PLUGIN_DIR}/{relative}"
        if path.is_symlink():
            found.append(f"`{name}`：符號連結；Codex 複製外掛時會略過它")
            continue
        if path.is_dir():
            continue
        for number, line in enumerate(read_lines(root, name) or [], 1):
            found += [f"`{name}:{number}`：寫死的{label}：{text}" for _, label, text in
                      personal_hits(line, tuple(("home-path", label, pattern) for label, pattern in HOME_PATHS))]
            if word:
                found += [f"`{name}:{number}`：這台的帳號名：{m.group(0)}" for m in word.finditer(line)]
    return found


# ---- 5 外掛資料夾凍結 ----

def plugin_entries(root: Path, modes) -> list[dict]:
    """外掛資料夾的清單：每個資料夾、檔案與符號連結一筆，依相對路徑排序。"""
    entries = []
    for relative, path in walk_plugin(root):
        if path.is_symlink():
            entries.append({"path": relative, "type": "symlink", "target": os.readlink(path)})
        elif path.is_dir():
            entries.append({"path": relative, "type": "dir"})
        else:
            if os.name == "nt":  # Windows 的檔案系統沒有可執行位元，改看 git 記的
                executable = modes.get(f"{PLUGIN_DIR}/{relative}") == "100755"
            else:
                executable = bool(path.lstat().st_mode & 0o100)
            entries.append({"path": relative, "type": "file", "executable": executable,
                            "sha256": sha256_bytes(path.read_bytes())})
    return sorted(entries, key=lambda entry: entry["path"])


def tree_sha256(entries) -> str:
    return sha256_text(json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def describe(entry: dict) -> str:
    if entry["type"] == "file":
        return f"檔案，{'可執行' if entry.get('executable') else '不可執行'}，sha256 {str(entry.get('sha256'))[:12]}…"
    return {"dir": "資料夾", "symlink": "符號連結"}.get(entry["type"], str(entry["type"]))


def read_lock(root: Path) -> tuple[dict | None, str | None]:
    """(登記, 問題)。登記檔不存在時兩個都是 None。"""
    if not (root / LOCK_FILE).exists():
        return None, None
    lock, problem = load_json(root, LOCK_FILE)
    if problem:
        return None, problem
    entries = lock.get("entries") if isinstance(lock, dict) else None
    if not (isinstance(entries, list) and isinstance(lock.get("tree_sha256"), str)
            and all(isinstance(entry, dict) and isinstance(entry.get("path"), str) and "type" in entry for entry in entries)):
        return None, f"`{LOCK_FILE}`：格式不對（要有 version、tree_sha256 與 entries）"
    return lock, None


def check_plugin_lock(root: Path, modes) -> list[str]:
    lock, problem = read_lock(root)
    if problem:
        return [problem]
    if lock is None:
        return [f"`{LOCK_FILE}`：`{PLUGIN_DIR}` 還沒有登記；執行 python3 -B scripts/release_check.py --write-plugin-lock"]
    if tree_sha256(lock["entries"]) != lock["tree_sha256"]:
        return [f"`{LOCK_FILE}`：tree_sha256 與它自己的 entries 對不上；登記檔不手改，用 --write-plugin-lock 重新產生"]
    entries = plugin_entries(root, modes)
    if tree_sha256(entries) == lock["tree_sha256"]:
        return []
    now = {entry["path"]: entry for entry in entries}
    then = {entry["path"]: entry for entry in lock["entries"]}
    details = []
    for path in sorted(set(now) | set(then)):
        name = f"`{PLUGIN_DIR}/{path}`"
        if path not in then:
            details.append(f"{name}：多出來的（{describe(now[path])}）")
        elif path not in now:
            details.append(f"{name}：不見了（登記的是{describe(then[path])}）")
        elif now[path] != then[path]:
            details.append(f"{name}：變了（登記的是{describe(then[path])}；現在是{describe(now[path])}）")
    return [f"`{PLUGIN_DIR}` 的內容與 `{LOCK_FILE}` 的登記不符（{len(details)} 處，列在下面）。"
            f"這個資料夾改任何一處，所有 Codex 使用者的 Hook 都會停到他們重新審查為止；確定要改的話，{LOCK_GUIDE}"] + details


def write_plugin_lock(root: Path, modes) -> int:
    """重新登記外掛資料夾。內容變了而外掛版本沒調時不寫。"""
    versions = plugin_versions(root)
    versions.pop(LOCK_FILE)
    version = versions[CLAUDE_MANIFEST]
    if len(set(versions.values())) != 1 or not isinstance(version, str):
        print("外掛版本不一致或缺漏，先對齊再登記：" + "、".join(f"{source} 是 {json.dumps(value)}" for source, value in versions.items()))
        return 1
    entries = plugin_entries(root, modes)
    digest = tree_sha256(entries)
    old, problem = read_lock(root)
    if problem:
        print(f"{problem}\n現有的登記讀不懂，無法確認外掛版本有沒有調；確認後刪掉它再重新登記。")
        return 1
    if old is not None and old["tree_sha256"] == digest and old.get("version") == version:
        print(f"`{PLUGIN_DIR}` 與登記相符（外掛版本 {version}），沒有要更新的。")
        return 0
    if old is not None and old["tree_sha256"] != digest and old.get("version") == version:
        print(f"`{PLUGIN_DIR}` 的內容變了，但外掛版本還是 {version}，沒有寫入。\n"
              f"先調外掛版本（兩份清單與 {CLAUDE_MARKETPLACE}），再跑一次；變更說明要寫「Codex 使用者要重新信任」。")
        return 1
    lock = {"schema_version": 1, "plugin": PLUGIN_NAME, "path": PLUGIN_DIR, "version": version,
            "tree_sha256": digest, "entries": entries}
    (root / LOCK_FILE).write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"已登記 `{PLUGIN_DIR}`（外掛版本 {version}，{len(entries)} 項，tree_sha256 {digest}）到 `{LOCK_FILE}`。")
    if old is not None:
        print("這次的變更說明要寫「Codex 使用者要重新信任」。")
    return 0


# ---- 6 授權 ----

def check_licenses(root: Path, files) -> list[str]:
    found = []
    if "LICENSE" not in files:
        found.append("`LICENSE`：沒有進版控")
    elif not (root / "LICENSE").is_file() or not (root / "LICENSE").read_bytes().strip():
        found.append("`LICENSE`：不存在或是空的")
    lock, problem = load_json(root, RUNTIME_LOCK)
    snapshot_name = LICENSE_SNAPSHOT + "/snapshot.json"
    try:
        raw = (root / snapshot_name).read_bytes()
        snapshot = json.loads(raw)
        listed = dict(snapshot["files"])
        expected = lock["licensing_snapshot_sha256"]
        source = {"provider": lock["provider"], "release": lock["release"], "runtime_sha256": lock["runtime"]["sha256"],
                  "licensing_sha256": lock["licensing_source"]["sha256"]}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return found + [problem or f"`{snapshot_name}` 或 `{RUNTIME_LOCK}`：讀不到授權快照的登記（{exc!r}）"]
    if sha256_bytes(raw) != expected:
        found.append(f"`{snapshot_name}`：雜湊與 `{RUNTIME_LOCK}` 的 licensing_snapshot_sha256 不一致")
    if snapshot.get("source") != source:
        found.append(f"`{snapshot_name}`：source 與 `{RUNTIME_LOCK}` 記的 runtime 來源不一致")
    prefix = LICENSE_SNAPSHOT + "/"
    present = {name[len(prefix):] for name in files if name.startswith(prefix)} - {"snapshot.json"}
    found += [f"`{prefix}{name}`：進了版控，但不在 snapshot.json 的 files 裡" for name in sorted(present - set(listed))]
    for name, info in sorted(listed.items()):
        if name not in present:
            found.append(f"`{prefix}{name}`：snapshot.json 有列，但沒有進版控")
            continue
        try:
            data = (root / prefix / name).read_bytes()
        except OSError:
            found.append(f"`{prefix}{name}`：讀不到")
            continue
        if not isinstance(info, dict) or len(data) != info.get("size") or sha256_bytes(data) != info.get("sha256"):
            found.append(f"`{prefix}{name}`：大小或雜湊與 snapshot.json 記的不一致")
    return found


# ---- 7 不該進版控的東西 ----

def check_tracked(files) -> list[str]:
    found = []
    for name in sorted(files):
        parts = name.split("/")
        if parts[-1] == ".DS_Store":
            found.append(f"`{name}`：macOS 的 Finder 資料進了版控")
        elif parts[-1] == "workspace-allowlist.local.json":
            found.append(f"`{name}`：這台的工作區白名單進了版控")
        elif DATABASE_FILE.search(parts[-1]):
            found.append(f"`{name}`：資料庫檔進了版控")
        else:
            found += [f"`{name}`：`{folder}/` 底下的東西進了版控" for folder in ("runtime", "dist") if folder in parts[:-1]]
    return found


def main(argv=None, root: Path | None = None, tags=None, account=...) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="MRH 發佈檢查：列出每一項違規；全過時結束碼 0。")
    ap.add_argument("--write-plugin-lock", action="store_true",
                    help=f"重新登記 {PLUGIN_DIR} 的內容到 {LOCK_FILE}（內容變了而外掛版本沒調時不寫）")
    a = ap.parse_args(argv)
    root = Path(root or ROOT)
    try:
        files = tracked(root)
        if a.write_plugin_lock:
            return write_plugin_lock(root, files)
        tags = release_tags(root) if tags is None else tags
    except CheckError as exc:
        print(f"無法檢查：{exc}")
        return 1
    account = local_account() if account is ... else account
    allow, allow_problems = load_allow(root)
    personal, unused, skipped = check_personal(root, files, allow)
    versions, notes = check_versions(root, files, tags)
    if skipped:
        notes.append(f"第 1 項有 {len(skipped)} 個檔讀不成文字（二進位檔或不在工作目錄），沒有掃：" + "、".join(f"`{name}`" for name in skipped))
    if not account:
        notes.append("第 4 項沒有比對帳號名（這台的帳號名太短、是 CI 這類不指向任何人的帳號，或等於公開的擁有者名稱）")
    sections = [
        ("1 個人內容", personal),
        ("1 個人內容的例外清單", allow_problems + unused),
        ("2 外掛結構", check_structure(root, files)),
        ("3 版本一致", versions),
        ("4 外掛資料夾的靜態內容", check_plugin_static(root, account)),
        ("5 外掛資料夾凍結", check_plugin_lock(root, files)),
        ("6 授權", check_licenses(root, files)),
        ("7 不該進版控的東西", check_tracked(files)),
    ]
    print(f"# MRH 發佈檢查（{root}，進版控的檔 {len(files)} 個）\n")
    for title, found in sections:
        print(f"## {title}（{len(found)}）")
        print("\n".join(f"- {item}" for item in found) if found else "- 無")
        print()
    if notes:
        print("## 提示（不算違規）")
        print("\n".join(f"- {item}" for item in notes))
        print()
    total = sum(len(found) for _, found in sections)
    print(f"共 {total} 項。" + ("" if total else "通過。"))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
