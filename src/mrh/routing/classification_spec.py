"""Shared classifier pins and ordered rubric; no provider or IO dependencies."""

SUBSCRIPTION_MODEL = 'gpt-6-luna'
TYPESAFE_MODEL = "jev-1.13.0"
RUBRIC_VERSION = "mrh-tier-v1"
RUBRIC = {
    "light": "Mechanical work with a directly checkable result.",
    "small": "Bounded work requiring simple comprehension.",
    "mid": "Substantial implementation, testing, or diagnosis.",
    "top": "Cross-system design, conflicting evidence, or a material tradeoff.",
}
