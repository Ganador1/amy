"""Entrypoint de servicios compartidos para compatibilidad retroactiva.

The compatibility exports are loaded lazily. Importing a focused service such
as ``app.services.orchestration`` must not initialize optional chemistry,
biology, and physics stacks (or their native libraries).
"""

from __future__ import annotations

__all__ = [
    "ComputationalBiologyService",
    "ComputationalChemistryService",
    "SolidStatePhysicsService",
]


def __getattr__(name: str):
    if name == "ComputationalBiologyService":
        from app.domains.biology.services.computational_biology import (
            ComputationalBiologyService,
        )

        return ComputationalBiologyService
    if name == "ComputationalChemistryService":
        from app.domains.chemistry.services.computational_chemistry import (
            ComputationalChemistryService,
        )

        return ComputationalChemistryService
    if name == "SolidStatePhysicsService":
        from app.domains.physics.services.solid_state_physics import (
            SolidStatePhysicsService,
        )

        return SolidStatePhysicsService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
