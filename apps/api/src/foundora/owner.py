from __future__ import annotations

import argparse
import asyncio
import getpass
import os

from foundora.auth.passwords import InvalidOwnerEmail, InvalidOwnerPassword
from foundora.auth.service import AuthService, OwnerAlreadyProvisioned
from foundora.infrastructure.database import close_database


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provision Foundora's single owner account")
    parser.add_argument("--email", required=True, help="Owner login email")
    parser.add_argument(
        "--password-env",
        help="Read the password from this environment variable instead of prompting",
    )
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Replace the existing owner's credentials and revoke every session",
    )
    return parser.parse_args()


def _password(arguments: argparse.Namespace) -> str:
    if arguments.password_env:
        value = os.environ.get(arguments.password_env)
        if value is None:
            raise SystemExit(f"Environment variable {arguments.password_env} is not set")
        return value
    first = getpass.getpass("Owner password: ")
    second = getpass.getpass("Confirm owner password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    return first


async def _run() -> int:
    arguments = _arguments()
    try:
        owner = await AuthService().provision_owner(
            arguments.email,
            _password(arguments),
            replace_existing=arguments.replace_existing,
        )
    except (InvalidOwnerEmail, InvalidOwnerPassword) as error:
        raise SystemExit(str(error)) from error
    except OwnerAlreadyProvisioned as error:
        raise SystemExit(
            "An owner already exists. Use --replace-existing only for an "
            "intentional credential reset."
        ) from error
    finally:
        await close_database()
    print(f"Owner provisioned: {owner.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
