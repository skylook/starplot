"""The optic factory can opt into an interactive backend without changing defaults."""

from starplot.mixins import CreateOpticMixin


class _Target(CreateOpticMixin):
    ra = 12.5
    dec = -3.5


class _StaticOptic:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _InteractiveOptic(_StaticOptic):
    pass


def test_create_optic_keeps_the_static_default(monkeypatch):
    import starplot

    monkeypatch.setattr(starplot, "OpticPlot", _StaticOptic)
    result = _Target().create_optic(resolution=512)

    assert type(result) is _StaticOptic
    assert result.kwargs == {"ra": 12.5, "dec": -3.5, "resolution": 512}


def test_create_optic_accepts_an_explicit_backend_class(monkeypatch):
    import starplot

    monkeypatch.setattr(starplot, "OpticPlot", _StaticOptic)
    result = _Target().create_optic(plot_class=_InteractiveOptic, resolution=512)

    assert type(result) is _InteractiveOptic
    assert result.kwargs == {"ra": 12.5, "dec": -3.5, "resolution": 512}
