"""Errors raised while validating or executing the JPGen pipeline."""


class ConfigurationError(ValueError):
    """Invalid pipeline or stage configuration."""


class PackingGenerationError(ValueError):
    """A validated configuration could not produce a particle packing."""
