"""Declarative questions and terminal interaction for configuration stages."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto

import questionary
from questionary import Choice


class Navigation(Enum):
    BACK = auto()
    CANCEL = auto()


@dataclass(frozen=True)
class MenuChoice:
    title: str
    value: object


@dataclass(frozen=True)
class Question:
    key: str
    message: str
    explanation: str
    example: str
    kind: str = "text"
    default: object | Callable[[dict], object] | None = None
    choices: Sequence[MenuChoice] | Callable[[dict], Sequence[MenuChoice]] = ()
    parser: Callable[[str, dict], object] | None = None
    after_answer: Callable[[object, dict], object] | None = None
    visible: Callable[[dict], bool] = lambda _answers: True

    def resolved_default(self, answers):
        return self.default(answers) if callable(self.default) else self.default

    def resolved_choices(self, answers):
        return self.choices(answers) if callable(self.choices) else self.choices


class InteractiveTerminal:
    """Questionary adapter with common navigation and inline help."""

    BACK_VALUE = "__jpgen_back__"
    CANCEL_VALUE = "__jpgen_cancel__"

    def print(self, message, style=None):
        questionary.print(message, style=style)

    def ask(self, question, answers, *, can_go_back):
        self.print(f"\n{question.explanation}", style="bold")
        self.print(f"Example: {question.example}", style="italic")
        if question.kind == "select":
            result = self._select(question, answers, can_go_back)
        else:
            result = self._text(question, answers, can_go_back)
        if isinstance(result, Navigation) or question.after_answer is None:
            return result
        return question.after_answer(result, answers)

    def choose(self, message, choices, *, can_go_back=True):
        options = [Choice(choice.title, value=choice.value) for choice in choices]
        if can_go_back:
            options.append(Choice("← Back", value=self.BACK_VALUE))
        options.append(Choice("✕ Cancel", value=self.CANCEL_VALUE))
        value = questionary.select(message, choices=options).unsafe_ask()
        return self._navigation(value)

    def _select(self, question, answers, can_go_back):
        choices = [
            Choice(choice.title, value=choice.value)
            for choice in question.resolved_choices(answers)
        ]
        if can_go_back:
            choices.append(Choice("← Back", value=self.BACK_VALUE))
        choices.append(Choice("✕ Cancel", value=self.CANCEL_VALUE))
        default = question.resolved_default(answers)
        value = questionary.select(
            question.message,
            choices=choices,
            default=default,
        ).unsafe_ask()
        return self._navigation(value)

    def _text(self, question, answers, can_go_back):
        parser = question.parser or (lambda value, _answers: value)

        def validate(value):
            token = value.strip().lower()
            if token == ":cancel" or (can_go_back and token == ":back"):
                return True
            try:
                parser(value, answers)
            except ValueError as error:
                return str(error)
            return True

        navigation = ":cancel"
        if can_go_back:
            navigation = ":back or :cancel"
        default = question.resolved_default(answers)
        value = questionary.text(
            question.message,
            default="" if default is None else str(default),
            instruction=f"(Enter {navigation})",
            validate=validate,
        ).unsafe_ask()
        token = value.strip().lower()
        if token == ":back" and can_go_back:
            return Navigation.BACK
        if token == ":cancel":
            return Navigation.CANCEL
        return parser(value, answers)

    def _navigation(self, value):
        if value == self.BACK_VALUE:
            return Navigation.BACK
        if value == self.CANCEL_VALUE:
            return Navigation.CANCEL
        return value


def run_questions(terminal, question_factory, answers=None, *, start_at=0):
    """Run a dynamic question list while preserving Back across branches."""
    answers = {} if answers is None else answers
    initial = [question for question in question_factory(answers) if question.visible(answers)]
    if start_at == "last":
        index = max(0, len(initial) - 1)
        if initial:
            answers.pop(initial[index].key, None)
    else:
        index = start_at
    visited = [question.key for question in initial[:index]]
    while True:
        questions = [question for question in question_factory(answers) if question.visible(answers)]
        visible_keys = {question.key for question in questions}
        for key in tuple(answers):
            if key not in visible_keys and key in visited:
                answers.pop(key, None)
        if index >= len(questions):
            return answers
        question = questions[index]
        result = terminal.ask(question, answers, can_go_back=index > 0)
        if result is Navigation.CANCEL:
            return None
        if result is Navigation.BACK:
            index = max(0, index - 1)
            for key in visited[index:]:
                answers.pop(key, None)
            answers.pop(questions[index].key, None)
            visited = visited[:index]
            continue
        answers[question.key] = result
        if index < len(visited):
            visited[index] = question.key
            del visited[index + 1:]
        else:
            visited.append(question.key)
        index += 1
