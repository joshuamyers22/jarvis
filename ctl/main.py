"""ctl -- deploy and operate the research platform.

Five commands. It stays five commands: anything that provisions infrastructure
belongs in Terraform, not here. That boundary is what stops this file becoming
a bespoke orchestration framework nobody remembers how to use.
"""

from __future__ import annotations

import typer

from ctl.commands import build, deploy, logs, run, shell

app = typer.Typer(
    name="ctl",
    help="Build, deploy and operate the research platform.",
    no_args_is_help=True,
    add_completion=False,
)

app.command("build")(build.build)
app.command("push")(build.push)
app.command("deploy")(deploy.deploy)
app.command("logs")(logs.logs)
app.command("shell")(shell.shell)
app.command("run")(run.run)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
