"""Errors raised while validating configuration or generating particles."""


class ConfigurationError(ValueError):
    """Invalid particle-generation configuration."""


class GenerationError(ValueError):
    """A validated configuration could not produce a particle set."""
