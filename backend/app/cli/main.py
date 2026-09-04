"""``rag`` CLI entrypoint (docs/ARCHITECTURE.md §4.1, §27.2).

rag version
rag config-check
rag bootstrap [--check-infra] [--skip-migrate]   migrate + admin + (optional) infra wait
rag reconcile [--once]                            run the reconciliation sweep
rag user create --email ... [--password ...] [--admin]
rag api-key create --email ... --name ... --scope ...  [--kb <uuid>]
rag eval ...                                      (Phase 9)
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

from app import __version__
from app.config import AuthMode, ConfigError, Settings, get_settings


def _load_settings() -> Settings | None:
    try:
        return get_settings()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return None


def _cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def _cmd_config_check(_args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    print("configuration OK")
    for key, value in settings.safe_summary().items():
        print(f"  {key}: {value}")
    return 0


async def _bootstrap_admin(settings: Settings) -> None:
    from app.core.security import hash_password
    from app.infra.db.repositories.users import UserRepository
    from app.infra.db.session import session_scope

    email = settings.bootstrap_admin_email
    password = settings.bootstrap_admin_password
    if not email:
        return
    async with session_scope(settings) as session:
        users = UserRepository(session)
        if await users.get_by_email(email) is not None:
            print(f"  admin user {email} already exists")
            return
        secret = password.get_secret_value() if password else secrets.token_urlsafe(18)
        users.add(
            email=email,
            password_hash=hash_password(secret),
            display_name="Administrator",
            is_admin=True,
        )
        if password is None:
            print(f"  created admin {email} with generated password: {secret}")
        else:
            print(f"  created admin {email}")


def _cmd_bootstrap(args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings is None:
        return 1

    from app.core.logging import configure_logging

    configure_logging(level=settings.app_log_level, json_output=settings.app_log_json)
    print("configuration OK")

    if args.check_infra:
        from app.services.health import HealthService, build_default_probes

        service = HealthService(build_default_probes(settings))
        report = asyncio.run(service.wait_until_ready(timeout_s=settings.bootstrap_wait_s))
        for dep in report.dependencies:
            mark = "ok  " if dep.state.value == "ok" else "FAIL"
            line = f"  [{mark}] {dep.name} ({dep.latency_ms} ms)"
            if dep.detail:
                line += f" — {dep.detail}"
            print(line)
        if not report.ready:
            print("infrastructure not ready", file=sys.stderr)
            return 1

    if not args.skip_migrate:
        from app.cli.migrations import upgrade_to_head

        upgrade_to_head()
        print("  migrations applied (alembic upgrade head)")

    if settings.auth_mode is AuthMode.MULTI_USER:
        asyncio.run(_bootstrap_admin(settings))

    if settings.seed_on_bootstrap:
        import importlib

        seed = importlib.import_module("app.cli.seed")
        asyncio.run(seed.seed_corpus(settings))

    print("bootstrap complete")
    return 0


def _cmd_reconcile(_args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    import importlib

    from app.core.logging import configure_logging

    configure_logging(level=settings.app_log_level, json_output=settings.app_log_json)
    reconcile = importlib.import_module("app.workers.reconcile")
    summary = asyncio.run(reconcile.reconcile_once(settings))
    print(f"reconcile: {summary}")
    return 0


async def _create_user(settings: Settings, *, email: str, password: str, admin: bool) -> None:
    from app.core.security import hash_password
    from app.infra.db.repositories.users import UserRepository
    from app.infra.db.session import session_scope

    async with session_scope(settings) as session:
        users = UserRepository(session)
        if await users.get_by_email(email) is not None:
            raise SystemExit(f"user {email} already exists")
        users.add(
            email=email,
            password_hash=hash_password(password),
            display_name=email.split("@")[0],
            is_admin=admin,
        )
    print(f"created user {email}" + (" (admin)" if admin else ""))


def _cmd_user_create(args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    password = args.password or secrets.token_urlsafe(18)
    asyncio.run(_create_user(settings, email=args.email, password=password, admin=args.admin))
    if not args.password:
        print(f"generated password: {password}")
    return 0


async def _create_api_key(
    settings: Settings, *, email: str, name: str, scopes: list[str], kb: str | None
) -> None:
    import uuid

    from app.core.enums import ActorType, ApiKeyScope
    from app.core.principal import Principal
    from app.infra.db.repositories.users import UserRepository
    from app.infra.db.session import session_scope
    from app.services.api_keys import ApiKeyService

    async with session_scope(settings) as session:
        user = await UserRepository(session).get_by_email(email)
        if user is None:
            raise SystemExit(f"no user with email {email}")
        principal = Principal(user_id=user.id, is_admin=user.is_admin, actor_type=ActorType.USER)
        service = ApiKeyService(session, settings)
        created = await service.create(
            principal,
            name=name,
            scopes=[ApiKeyScope(s) for s in scopes],
            knowledge_base_id=uuid.UUID(kb) if kb else None,
            request_id=None,
        )
        print(f"API key created (shown once): {created.token}")


def _cmd_api_key_create(args: argparse.Namespace) -> int:
    settings = _load_settings()
    if settings is None:
        return 1
    asyncio.run(
        _create_api_key(settings, email=args.email, name=args.name, scopes=args.scope, kb=args.kb)
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rag", description="enterprise-rag-platform CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version").set_defaults(func=_cmd_version)
    sub.add_parser("config-check").set_defaults(func=_cmd_config_check)

    bootstrap = sub.add_parser("bootstrap")
    bootstrap.add_argument("--check-infra", action="store_true")
    bootstrap.add_argument("--skip-migrate", action="store_true")
    bootstrap.set_defaults(func=_cmd_bootstrap)

    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--once", action="store_true", default=True)
    reconcile.set_defaults(func=_cmd_reconcile)

    user = sub.add_parser("user").add_subparsers(dest="user_command", required=True)
    user_create = user.add_parser("create")
    user_create.add_argument("--email", required=True)
    user_create.add_argument("--password")
    user_create.add_argument("--admin", action="store_true")
    user_create.set_defaults(func=_cmd_user_create)

    apikey = sub.add_parser("api-key").add_subparsers(dest="apikey_command", required=True)
    apikey_create = apikey.add_parser("create")
    apikey_create.add_argument("--email", required=True)
    apikey_create.add_argument("--name", required=True)
    apikey_create.add_argument("--scope", action="append", required=True)
    apikey_create.add_argument("--kb")
    apikey_create.set_defaults(func=_cmd_api_key_create)

    _register_eval_commands(sub)
    return parser


def _register_eval_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Registered lazily so the CLI keeps working if the eval extra is trimmed."""

    import importlib.util

    if importlib.util.find_spec("app.cli.evalcmd") is None:  # pragma: no cover
        return
    import importlib

    evalcmd = importlib.import_module("app.cli.evalcmd")
    evalp = sub.add_parser("eval").add_subparsers(dest="eval_command", required=True)
    evalcmd.register(evalp)
    evalcmd.register_traces(sub)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
