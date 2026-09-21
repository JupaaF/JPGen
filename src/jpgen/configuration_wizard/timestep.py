"""Fixed DEM time-step question."""
from .questions import Question


def time_step_questions(answers):
    return [Question(
        key='dem.time_step', message='Fixed time step (s)', default=1e-6,
        explanation='Physical time advanced by each DEM step. Choose a positive value small enough to resolve contacts; smaller or stiffer particles generally need smaller steps.',
        example='1e-6', parser=lambda value, _: float(value),
    )]


def build_time_step(answers):
    return answers['dem.time_step']
