"""Orchestrate interactive stage configuration before pipeline execution."""

import os
from datetime import datetime
from pathlib import Path

from .dem import DemStageWizard
from .output import GeneratedConfiguration, render_yaml
from .packing import PackingStageWizard
from .questions import InteractiveTerminal, MenuChoice, Navigation, Question, run_questions


class ConfigurationWizard:
    """Collect, validate, preview and publish one pipeline configuration."""

    def __init__(self, stages, terminal=None, current_directory=None, clock=None):
        self.stages = tuple(stages)
        self.terminal = terminal or InteractiveTerminal()
        self.current_directory = Path(current_directory or Path.cwd())
        self.clock = clock or datetime.now

    def run(self):
        timestamp = self.clock().strftime("%Y-%m-%d_%H-%M-%S")
        default_name = f"jpgen_{timestamp}.yaml"
        answers = {}
        start_at = 0
        try:
            while True:
                result = run_questions(
                    self.terminal,
                    lambda current: self._questions(current, default_name),
                    answers,
                    start_at=start_at,
                )
                if result is None:
                    return None
                answers = result
                try:
                    configuration = self._validated_configuration(answers)
                except (KeyError, ValueError, OverflowError) as error:
                    self.terminal.print(f"Configuration error: {error}", style="fg:red bold")
                    action = self.terminal.choose(
                        "Return to the last question?",
                        (MenuChoice("Yes", "back"),),
                    )
                    if action is Navigation.CANCEL:
                        return None
                    start_at = "last"
                    continue
                rendered = render_yaml(configuration)
                self.terminal.print("\nConfiguration preview", style="bold")
                self.terminal.print(rendered)
                action = self.terminal.choose(
                    "Save this configuration and start JPGen?",
                    (MenuChoice("Save and run", "save"),),
                )
                if action is Navigation.CANCEL:
                    return None
                if action is Navigation.BACK:
                    start_at = "last"
                    continue
                return GeneratedConfiguration.publish(answers["output.path"], rendered)
        except (KeyboardInterrupt, EOFError):
            return None

    def _questions(self, answers, default_name):
        questions = [
            Question(
                key="output.path",
                message="YAML output path",
                explanation="File to create. Relative paths use the directory where JPGen was launched; directories receive the timestamped filename.",
                example=default_name,
                default=str(self.current_directory / default_name),
                parser=lambda value, _answers: self._output_path(value, default_name),
            ),
            Question(
                key="output.overwrite",
                message="The selected YAML file already exists",
                explanation="JPGen needs explicit confirmation before replacing the existing file. It can restore the original if generation fails.",
                example="Choose overwrite only when the selected path is correct.",
                kind="select",
                choices=(MenuChoice("Yes, overwrite the existing file", True),),
                visible=lambda current: current.get("output.path", Path("/__missing__")).exists(),
            ),
        ]
        for stage in self.stages:
            questions.extend(stage.questions(answers, self.terminal))
        return questions

    def _validated_configuration(self, answers):
        configuration = {}
        for stage in self.stages:
            value = stage.validate(stage.build(answers))
            if value is not None:
                name = stage.section_name(answers) if hasattr(stage, "section_name") else stage.name
                configuration[name] = value
        return configuration

    def _output_path(self, value, default_name):
        raw = value.strip()
        if not raw:
            path = self.current_directory / default_name
        else:
            expanded = Path(raw).expanduser()
            path = expanded if expanded.is_absolute() else self.current_directory / expanded
            if raw.endswith((os.sep, "/")) or path.is_dir():
                path /= default_name
            elif not path.suffix:
                path = path.with_suffix(".yaml")
        if path.suffix != ".yaml":
            raise ValueError("The output file must use the .yaml extension.")
        if path.is_symlink():
            raise ValueError("The output path must not be a symbolic link.")
        if path.exists() and not path.is_file():
            raise ValueError("The output path exists and is not a regular file.")
        return path.absolute()


def build_configuration_wizard():
    """Compose the default wizard and its stage contributions."""
    return ConfigurationWizard((PackingStageWizard(), DemStageWizard()))
