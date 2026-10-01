"""Persistent Textual interface for the synchronous configuration workflow."""

from concurrent.futures import Future
from dataclasses import dataclass
from threading import Event, Lock, Thread

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import (
    Button, Footer, Header, Input, OptionList, ProgressBar, SelectionList, Static,
)

from .questions import MenuChoice, Navigation


@dataclass(frozen=True)
class Prompt:
    message: str
    kind: str
    default: object = None
    choices: tuple[MenuChoice, ...] = ()
    explanation: str = ""
    example: str = ""
    section: str = "Review"
    can_go_back: bool = True
    progress: tuple[int, int] | None = None


class PromptRequested(Message):
    def __init__(self, prompt, future, messages, error):
        super().__init__()
        self.prompt, self.future, self.messages, self.error = prompt, future, messages, error


class WorkflowFinished(Message):
    def __init__(self, result, failure=None):
        super().__init__()
        self.result, self.failure = result, failure


class InteractiveTerminal:
    """Bridge question collection to one Textual app, keeping work off the UI thread."""

    def __init__(self):
        self._progress = None
        self._messages = []
        self._cancelled = Event()
        self._lock = Lock()
        self._pending = None
        self.app = None

    def run(self, workflow):
        self._cancelled.clear()
        self._messages.clear()
        self._progress = None
        self.app = WizardApp(self, workflow)
        result = self.app.run()
        if self.app.failure is not None:
            raise self.app.failure
        return result

    def set_progress(self, current, total):
        self._progress = (current, total)

    def print(self, message, style=None):
        # Text stays literal: user paths and YAML must not be interpreted as markup.
        rich_style = "bold red" if style and "red" in style else "bold" if style else ""
        self._messages.append(Text(str(message), style=rich_style))

    def _check_cancelled(self):
        if self._cancelled.is_set():
            raise EOFError

    def _wait(self, prompt, *, error=None):
        future = Future()
        with self._lock:
            self._check_cancelled()
            self._pending = future
        messages, self._messages = self._messages, []
        self.app.post_message(PromptRequested(prompt, future, messages, error))
        while True:
            try:
                result = future.result(timeout=0.1)
                break
            except TimeoutError:
                if not self.app.is_running:
                    self.cancel()
                self._check_cancelled()
        self._check_cancelled()
        return result

    def resolve(self, future, result):
        with self._lock:
            if future is not None and not future.done():
                future.set_result(result)

    def cancel(self):
        with self._lock:
            self._cancelled.set()
            if self._pending is not None and not self._pending.done():
                self._pending.set_result(Navigation.CANCEL)

    def ask(self, question, answers, *, can_go_back):
        prompt = Prompt(
            message=question.message,
            kind=question.kind,
            default=question.resolved_default(answers),
            choices=tuple(question.resolved_choices(answers)),
            explanation=question.explanation,
            example=question.example,
            section=question.key.split(".", 1)[0].replace("_", " ").title(),
            can_go_back=can_go_back,
            progress=self._progress,
        )
        error = None
        while True:
            result = self._wait(prompt, error=error)
            if isinstance(result, Navigation):
                return result
            try:
                if question.kind == "text" and question.parser is not None:
                    result = question.parser(result, answers)
                if question.after_answer is not None:
                    result = question.after_answer(result, answers)
                self._check_cancelled()
                return result
            except (ValueError, OverflowError) as invalid:
                error = str(invalid)

    def choose(self, message, choices, *, can_go_back=True):
        return self._wait(Prompt(
            message=message, kind="select", choices=tuple(choices), can_go_back=can_go_back,
        ))


class WizardApp(App):
    """Mouse-driven forms, navigation and configuration review in the terminal."""

    TITLE = "JPGen"
    SUB_TITLE = "Configuration wizard"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "cancel", "Cancel", priority=True),
        Binding("alt+left", "back", "Back"),
    ]
    CSS = """
    Screen { background: $background; }
    #layout { height: 1fr; }
    #sidebar { width: 23; padding: 1 2; border-right: solid $primary; }
    #brand { text-style: bold; color: $accent; margin-bottom: 1; }
    .stage { height: auto; padding: 1 0; color: $text-muted; }
    .stage.active { color: $accent; text-style: bold; }
    #step { height: auto; margin-top: 1; color: $text-muted; }
    #progress { margin-top: 1; width: 100%; }
    #main { width: 1fr; }
    #form { height: 1fr; padding: 1 2; }
    #question { height: auto; text-style: bold; color: $accent; margin-bottom: 1; }
    #explanation { height: auto; margin-bottom: 1; }
    #example { height: auto; color: $text-muted; margin-bottom: 1; }
    #editor { height: auto; }
    #editor Input { width: 100%; }
    #editor OptionList { height: auto; max-height: 16; border: round $primary; }
    #editor SelectionList { height: auto; max-height: 16; border: round $primary; }
    #error { height: auto; color: $error; margin-top: 1; }
    #context { height: 12; min-height: 5; margin-bottom: 1; border: round $primary; }
    #form.review #context { height: 1fr; min-height: 8; }
    #actions { height: auto; padding: 1 2; border-top: solid $primary; }
    #actions Button { width: auto; margin-right: 1; min-width: 10; }
    .narrow #sidebar { display: none; }
    .narrow #actions { padding: 0 1; }
    .narrow #actions Button { min-width: 8; margin-right: 0; }
    """

    def __init__(self, terminal, workflow):
        super().__init__()
        self.terminal = terminal
        self.workflow = workflow
        self.failure = None
        self.prompt = None
        self.pending = None
        self._saving = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="layout"):
            with Vertical(id="sidebar"):
                yield Static("CONFIGURATION", id="brand")
                yield Static("1  Output file", id="stage-output", classes="stage")
                yield Static("2  Packing", id="stage-packing", classes="stage")
                yield Static("3  DEM", id="stage-dem", classes="stage")
                yield Static("4  Review & run", id="stage-review", classes="stage")
                yield Static("Preparing…", id="step", markup=False)
                yield ProgressBar(total=1, show_eta=False, show_percentage=False, id="progress")
            with Vertical(id="main"):
                with VerticalScroll(id="form"):
                    yield Static("Preparing configuration…", id="question", markup=False)
                    yield Static("", id="explanation", markup=False)
                    yield Static("", id="example", markup=False)
                    with VerticalScroll(id="context"):
                        yield Static("", id="preview", markup=False)
                    yield Container(id="editor")
                    yield Static("", id="error", markup=False)
                with Horizontal(id="actions"):
                    yield Button("← Back", id="back", disabled=True)
                    yield Button("Continue →", id="continue", variant="primary", disabled=True)
                    yield Button("Cancel", id="cancel", variant="error")
        yield Footer()

    def on_mount(self):
        self.query_one("#context").display = False
        self.query_one("#error").display = False
        Thread(target=self._run_workflow, name="jpgen-wizard", daemon=True).start()

    def on_resize(self, event):
        self.screen.set_class(event.size.width < 72, "narrow")

    def _run_workflow(self):
        failure = None
        try:
            result = self.workflow()
        except (KeyboardInterrupt, EOFError):
            result = None
        except Exception as error:
            failure = error
            result = None
        if not self.terminal._cancelled.is_set():
            self.post_message(WorkflowFinished(result, failure))

    def on_workflow_finished(self, event: WorkflowFinished):
        self.failure = event.failure
        self.exit(event.result)

    async def on_prompt_requested(self, event: PromptRequested):
        if self.terminal._cancelled.is_set():
            return
        if event.error is None:
            await self.show_prompt(event.prompt, event.future, event.messages)
        else:
            self.retry_prompt(event.future, event.error)

    async def show_prompt(self, prompt, future, messages):
        self.prompt = prompt
        self.pending = future
        form = self.query_one("#form", VerticalScroll)
        form.set_class(prompt.section == "Review", "review")
        form.scroll_home(animate=False)
        self.query_one("#question", Static).update(prompt.message)
        self.query_one("#explanation", Static).update(prompt.explanation)
        example = self.query_one("#example", Static)
        example.update(f"Example: {prompt.example}" if prompt.example else "")
        example.display = bool(prompt.example)
        error = self.query_one("#error", Static)
        error.update("")
        error.display = False
        context = self.query_one("#context", VerticalScroll)
        context.display = bool(messages)
        renderables = []
        for message in messages:
            content = message.plain
            if "\n" in content and content.startswith(("packing:", "packing_source:", "units:", "dem:")):
                renderables.append(Syntax(content, "yaml", word_wrap=True))
            else:
                renderables.append(message)
        self.query_one("#preview", Static).update(Group(*renderables))
        context.scroll_home(animate=False)
        section = prompt.section.lower()
        active = "output" if section == "output" else "dem" if section == "dem" else "review" if section == "review" else "packing"
        for stage in ("output", "packing", "dem", "review"):
            self.query_one(f"#stage-{stage}").set_class(stage == active, "active")
        step = self.query_one("#step", Static)
        progress = self.query_one("#progress", ProgressBar)
        if prompt.progress:
            current, total = prompt.progress
            step.update(f"{prompt.section}\nQuestion {current} of {total}\nSteps adapt to your choices")
            progress.update(total=total, progress=current - 1)
        else:
            step.update("Review configuration")
            progress.update(total=1, progress=1)
        editor = self.query_one("#editor", Container)
        single_review = len(prompt.choices) == 1 and prompt.section == "Review"
        editor.display = not single_review
        await editor.remove_children()
        if prompt.kind == "select":
            widget = OptionList(*(Text(choice.title) for choice in prompt.choices), id="answer")
            widget.highlighted = next(
                (i for i, choice in enumerate(prompt.choices) if choice.value == prompt.default), 0,
            )
        elif prompt.kind == "checkbox":
            selected = prompt.default or []
            widget = SelectionList(*(
                (Text(choice.title), i, choice.value in selected)
                for i, choice in enumerate(prompt.choices)
            ), id="answer")
        else:
            widget = Input(value="" if prompt.default is None else str(prompt.default), id="answer")
        await editor.mount(widget)
        self._enable_actions()
        if single_review:
            self.query_one("#continue", Button).label = prompt.choices[0].title
        else:
            self.query_one("#continue", Button).label = "Continue →"
        if single_review:
            self.query_one("#continue", Button).focus()
        else:
            widget.focus()

    def _enable_actions(self):
        self.query_one("#continue", Button).disabled = False
        self.query_one("#back", Button).disabled = not self.prompt.can_go_back
        self.query_one("#answer").disabled = False

    def retry_prompt(self, future, error):
        self.pending = future
        message = self.query_one("#error", Static)
        message.update(error)
        message.display = True
        self._enable_actions()
        message.scroll_visible(animate=False)
        self.query_one("#answer").focus()

    def _answer(self, result):
        if self.pending is None or self.pending.done():
            return
        self.query_one("#continue", Button).disabled = True
        self.query_one("#back", Button).disabled = True
        self.query_one("#answer").disabled = True
        if self.prompt.section == "Review" and result == "save":
            self._saving = True
            self.query_one("#cancel", Button).disabled = True
        self.terminal.resolve(self.pending, result)

    def action_continue(self):
        if self.prompt is None or self.pending is None or self.pending.done():
            return
        widget = self.query_one("#answer")
        if self.prompt.kind == "select":
            if widget.highlighted is None:
                return
            result = self.prompt.choices[widget.highlighted].value
        elif self.prompt.kind == "checkbox":
            selected = set(widget.selected)
            result = [choice.value for i, choice in enumerate(self.prompt.choices) if i in selected]
        else:
            result = widget.value
        self._answer(result)

    def action_back(self):
        if self.prompt is not None and self.prompt.can_go_back:
            self._answer(Navigation.BACK)

    def action_cancel(self):
        if self._saving:
            return
        self.terminal.cancel()
        self.exit(None)

    def on_unmount(self):
        self.terminal.cancel()

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "continue":
            self.action_continue()
        elif event.button.id == "back":
            self.action_back()
        elif event.button.id == "cancel":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted):
        if event.input is self.query_one("#answer"):
            self.action_continue()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        if (
            self.prompt is not None and self.prompt.kind == "select"
            and event.option_list is self.query_one("#answer")
        ):
            self.action_continue()
