"""Settings-selected provider. No implicit conversion or provider fallback."""
from .core import ClassifierFailure
from .codex_subscription import CodexSubscriptionClassifier, MODEL
from .typesafe import classifier_from_config as typesafe_factory
from .typesafe_protocol import PINNED_MODEL

PROVIDERS={'codex_subscription':MODEL,'typesafe':PINNED_MODEL}


def classifier_from_config(config, **injected):
    if not isinstance(config,dict) or set(config)-{'provider','schema_version','model','enabled','task_export_permitted'}:
        raise ClassifierFailure('invalid_policy')
    provider=config.get('provider')
    if provider not in PROVIDERS or config.get('model')!=PROVIDERS[provider] or type(config.get('schema_version')) is not int or config['schema_version']!=1:
        raise ClassifierFailure('invalid_policy')
    if any(type(config.get(k)) is not bool for k in ('enabled','task_export_permitted')):
        raise ClassifierFailure('invalid_policy')
    if provider=='typesafe':
        return typesafe_factory({k:v for k,v in config.items() if k!='provider'},**injected)
    if set(injected)-{'subscription_runner','subscription_binding'}:raise ClassifierFailure('invalid_policy')
    return CodexSubscriptionClassifier(enabled=config['enabled'],task_export_permitted=config['task_export_permitted'],
                                       runner=injected.get('subscription_runner'),scope_binding=injected.get('subscription_binding'))
