"""Generate the scrypt hash to store as GOV_INVITE_CODE in secrets.toml."""
from getpass import getpass

from core.auth import hash_government_invite

if __name__ == "__main__":
    invite = getpass("Government invite code (input is hidden): ")
    print(hash_government_invite(invite))
