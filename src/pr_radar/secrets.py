import shlex
import subprocess


class SecretError(Exception):
    pass


def read_secret(command: str) -> str:
    """Runs a command such as `gh auth token`, so no secret is ever stored in the config file."""
    result = subprocess.run(shlex.split(command), capture_output=True, text=True, timeout=15)
    secret = result.stdout.strip()
    if result.returncode != 0 or not secret:
        raise SecretError(f"Command `{command}` did not return a secret")
    return secret
