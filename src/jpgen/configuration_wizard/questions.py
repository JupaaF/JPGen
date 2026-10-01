"""Declarative questions and terminal interaction for configuration stages."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto


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
        if hasattr(terminal, "set_progress"):
            terminal.set_progress(index + 1, len(questions))
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
