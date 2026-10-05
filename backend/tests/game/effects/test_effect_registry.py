"""Effect registry bootstrap tests."""

from mtg_analyzer.game.effects import bootstrap


def test_effect_registry_is_available_from_the_package_bootstrap():
    registry = bootstrap()
    assert registry.is_registered("draw")


def test_effect_registry_bootstrap_is_idempotent():
    assert bootstrap() is bootstrap()
