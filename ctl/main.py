"""ctl -- deploy and operate the research platform.

Infrastructure provisioning belongs in Terraform. This CLI contains only image,
release, and day-two workload operations.
"""

from __future__ import annotations

import typer

from ctl.commands import build, deploy, logs, migrate, run, shell

app = typer.Typer(
    name="ctl",
    help="Build, deploy and operate the research platform.",
    no_args_is_help=True,
    add_completion=False,
)

app.command("build")(build.build)
app.command("push")(build.push)
app.command("deploy")(deploy.deploy)
app.command("migrate")(migrate.migrate)
app.command("logs")(logs.logs)
app.command("shell")(shell.shell)
app.command("run")(run.run)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
