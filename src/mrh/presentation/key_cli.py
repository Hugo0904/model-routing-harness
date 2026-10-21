"""`mrh key`: manage the classifier credential without ever displaying it."""
from mrh.infrastructure import secrets

HELP = {"jev": "TypeSafe API 金鑰（Jev 分級器用）"}


def run(action, name, *, stdout, stderr, secrets_module=secrets):
    if name not in HELP:
        stderr.write("mrh: 不認識這個金鑰名稱\n")
        return 2
    if action == "status":
        env = secrets.ENV_VARS[name]
        import os
        stdout.write(f"{name}: {HELP[name]}\n")
        stdout.write(f"  環境變數 {env}：{'已設定' if os.environ.get(env) else '未設定'}\n")
        store = 'Windows Credential Manager' if os.name == 'nt' else 'Keychain'
        stdout.write(f"  {store}：{'已設定' if secrets_module.is_set(name) else '未設定'}\n")
        return 0
    if action == "set":
        import os
        stdout.write("請在 Windows 原生視窗的密碼欄輸入 Jev 金鑰，會存入目前使用者的 Credential Manager。\n" if os.name == 'nt' else "接下來由 macOS 請你輸入金鑰（輸入時不會顯示），只會存進你的 Keychain，不會經過 MRH。\n")
        stdout.flush()
        try:
            secrets_module.store_interactively(name)
        except secrets.SecretError:
            stderr.write("mrh: 金鑰沒有存入\n")
            return 2
        stdout.write("已存入。可用這個指令確認：mrh key status " + name + "\n")
        return 0
    if action == "delete":
        stdout.write("已刪除。\n" if secrets_module.delete(name) else "沒有可刪除的金鑰。\n")
        return 0
    return 2
