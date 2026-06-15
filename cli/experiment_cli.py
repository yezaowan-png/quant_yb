"""Experiment command group."""

from pathlib import Path

import click
import yaml

from experiment.runner import run_experiment


def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


@click.group(name="experiment")
def experiment_group():
    """实验配置：从 YAML 运行可归档回测任务。"""
    pass


@experiment_group.command(name="run")
@click.argument("config_path")
def run(config_path: str):
    """运行一个 YAML 实验配置。"""
    project_config = _load_config()
    manifest = run_experiment(project_config, config_path)

    click.echo(f"实验已完成: {manifest['id']}")
    click.echo(f"  状态: {manifest['status']}")
    counts = manifest.get("result_counts", {})
    click.echo(
        f"  标的: {counts.get('succeeded', 0)}/{counts.get('requested', 0)} 成功"
    )
    outputs = manifest.get("outputs", {})
    click.echo(f"  输出目录: {manifest['output_dir']}")
    if outputs.get("summary"):
        click.echo(f"  汇总: {outputs['summary']}")
    click.echo(f"  manifest: {outputs.get('manifest', '')}")
