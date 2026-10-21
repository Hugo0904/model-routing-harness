"""Claude metadata version gate; catalog protocol support is a separate fact."""
import re

MIN_VERSION = (2, 1, 296)


def require_version(text):
    match = re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*) \(Claude Code\)', text) if isinstance(text, str) else None
    if not match:
        raise ValueError('claude_cli_version_unknown:無法辨識 Claude Code 版本')
    version = tuple(int(n) for n in match.groups())
    if version < MIN_VERSION:
        raise ValueError('claude_cli_version_too_old:請更新 Claude Code 至 2.1.296 或更新版本')
    return version
