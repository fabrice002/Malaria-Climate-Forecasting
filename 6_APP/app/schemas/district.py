"""
District schemas — the read contract for the dashboard's map layer.

The `districts` table already holds everything the frontend needs to place and
colour a marker (coordinates, population, regional threshold). This exposes it
read-only; districts are seeded from the model bundle at startup and are not
editable through the API.
"""

from pydantic import BaseModel, Field


class DistrictOut(BaseModel):
    """One health district, as the dashboard consumes it."""

    id: int
    name: str = Field(..., examples=["Biyem Assi"])
    region: str = Field(..., examples=["Centre"])

    lat: float = Field(..., description="Centroid latitude (WGS84).")
    lon: float = Field(..., description="Centroid longitude (WGS84).")
    area_km2: float = Field(..., description="District area.")
    cluster: int = Field(..., description="Ecological-zone cluster label.")

    population: int
    threshold: float = Field(
        ...,
        description="Per-region 75th-percentile incidence (per 1 000) above "
                    "which a month is classified High.",
    )
