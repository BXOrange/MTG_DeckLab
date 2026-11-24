"""Variable payment followed by effects using the recorded amounts."""
from .composition import _CompositeEffect, _build
from .core import _controller_of


class AmountPaymentEffect(_CompositeEffect):
    def __init__(self, resource, scope, repeat=False, effects=None, source=None):
        super().__init__(effects, source)
        self.resource = resource
        self.scope = scope
        self.repeat = repeat

    @property
    def target_specs(self):
        # RULE 601.2c: the payoff's targets are announced with the spell.
        return [spec for effect in _build(self.inner_specs, self.source) for spec in effect.target_specs]

    def apply(self, context, targets=None):
        controller = _controller_of(self.source, context)
        if controller is not None:
            context.engine._request_amount_payment(
                self.source, targets, controller.id, self.resource, self.scope, self.repeat, self.inner_specs,
            )
