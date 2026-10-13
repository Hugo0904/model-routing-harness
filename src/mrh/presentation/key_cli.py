"""`mrh key`: manage the classifier credential without ever displaying it."""
from mrh.infrastructure import secrets

HELP = {"jev": "TypeSafe API key (Jev classifier)"}


def run(action, name, *, stdout, stderr, secrets_module=secrets):
    if name not in HELP:
        stderr.write("mrh: unknown key name\n")
        return 2
    if action == "status":
        env = secrets.ENV_VARS[name]
        import os
        stdout.write(f"{name}: {HELP[name]}\n")
        stdout.write(f"  environment {env}: {'set' if os.environ.get(env) else 'not set'}\n")
        stdout.write(f"  Keychain: {'set' if secrets_module.is_set(name) else 'not set'}\n")
        return 0
    if action == "set":
        stdout.write("macOS will ask you to type the key (hidden). It is stored in your Keychain only.\n")
        stdout.flush()
        try:
            secrets_module.store_interactively(name)
        except secrets.SecretError:
            stderr.write("mrh: key was not stored\n")
            return 2
        stdout.write("Stored. Check with: mrh key status " + name + "\n")
        return 0
    if action == "delete":
        stdout.write("Deleted.\n" if secrets_module.delete(name) else "Nothing to delete.\n")
        return 0
    return 2
