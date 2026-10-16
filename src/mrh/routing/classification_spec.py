"""Shared classifier pins and ordered rubric; no provider or IO dependencies."""

SUBSCRIPTION_MODEL = 'gpt-6-luna'
import re

TYPESAFE_MODEL = "jev-1.13.0"          # the version this rubric was built and checked against
JEV_ALIASES = ("jev-latest", "jev-preview")   # TypeSafe aliases move when a new release ships
DEFAULT_JEV_MODEL = "jev-latest"       # new installs; an existing setting is never rewritten
_JEV_VERSION = re.compile(r"jev-\d{1,3}\.\d{1,3}\.\d{1,3}")


def is_jev_model(value):
    """An alias, or an exact version such as jev-1.14.0."""
    return isinstance(value, str) and (value in JEV_ALIASES or _JEV_VERSION.fullmatch(value) is not None)


def is_jev_alias(value):
    return value in JEV_ALIASES
RUBRIC_VERSION = "mrh-tier-v1"
RUBRIC = {
    "light": "Mechanical work with a directly checkable result.",
    "small": "Bounded work requiring simple comprehension.",
    "mid": "Substantial implementation, testing, or diagnosis.",
    "top": "Cross-system design, conflicting evidence, or a material tradeoff.",
}
