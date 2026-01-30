from __future__ import annotations
import click
import importlib

class LazyGroup(click.Group):
    def __init__(self, *args, lazy_subcommands: dict[str, tuple[str, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lazy_subcommands = lazy_subcommands or {}

    def list_commands(self, ctx: click.Context) -> list[str]:
        base = super().list_commands(ctx)
        lazy = sorted(self.lazy_subcommands.keys())
        return sorted(set(base + lazy))

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name in self.lazy_subcommands:
            return self._lazy_load(cmd_name)
        return super().get_command(ctx, cmd_name)

    def _lazy_load(self, cmd_name: str) -> click.Command:
        import_path, obj_name = self.lazy_subcommands[cmd_name]
        mod = importlib.import_module(import_path)
        return getattr(mod, obj_name)


COMMAND_MAPPING = {
    # Core
    "run": ("skillos.cli.commands.core", "run_query"),
    
    # Skills
    "add-skill": ("skillos.cli.commands.skills", "add_skill"),
    "run-skill": ("skillos.cli.commands.skills", "run_skill"),
    "validate": ("skillos.cli.commands.skills", "validate_command"),
    "test": ("skillos.cli.commands.skills", "test_skill"),
    "eval-skill": ("skillos.cli.commands.skills", "eval_skill"),
    "deprecate-skill": ("skillos.cli.commands.skills", "deprecate_skill_command"),
    "undeprecate-skill": ("skillos.cli.commands.skills", "undeprecate_skill_command"),

    # Pipeline
    "pipeline": ("skillos.cli.commands.pipeline", "pipeline"),
    "compose-skill": ("skillos.cli.commands.pipeline", "compose_skill"),
    "activate-skill": ("skillos.cli.commands.pipeline", "activate_skill"),
    
    # Marketplace
    "marketplace": ("skillos.cli.commands.market", "marketplace"),
    
    # Analysis
    "feedback": ("skillos.cli.commands.analysis", "feedback"),
    "optimize": ("skillos.cli.commands.analysis", "optimize_skill"),
    "metrics": ("skillos.cli.commands.analysis", "metrics_report"),
    
    # Infra & Connectors
    "secrets": ("skillos.cli.commands.infra", "secrets"),
    "suggestions": ("skillos.cli.commands.infra", "suggestions"),
    "schedule": ("skillos.cli.commands.infra", "schedule"),
    "webhook": ("skillos.cli.commands.infra", "webhook"),
    "job": ("skillos.cli.commands.infra", "job"),
    "add-connector": ("skillos.cli.commands.infra", "add_connector"),
}


@click.group(cls=LazyGroup, lazy_subcommands=COMMAND_MAPPING)
def cli() -> None:
    """SkillOS command line interface."""


# Preload the run command for test harnesses that access cli.commands directly.
try:
    cli.commands["run"] = cli._lazy_load("run")
except Exception:
    pass


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
