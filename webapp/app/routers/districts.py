"""
District router — read-only catalogue for the dashboard.

Endpoints (under the configured prefix, default /api/v1):
  GET /districts          list districts, optionally filtered by region
  GET /districts/{name}   one district by name

Districts are seeded from the model bundle's district_static.csv at startup, so
this is a read-only view: the dashboard needs coordinates, population and the
regional threshold to draw and colour its map.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.orm import District
from app.schemas.district import DistrictOut

router = APIRouter()


def _to_out(d: District) -> DistrictOut:
    # NOTE — the SHP_lat / SHP_lon columns in district_static.csv are TRANSPOSED:
    # `shp_lat` holds the longitude and `shp_lon` holds the latitude. Verified
    # against known coordinates (Biyem Assi, Kribi, Limbe, Bertoua, Maroua):
    # swapping gives a ~0.06 deg match, taking them as named is off by 7-18 deg.
    #
    # The models are unaffected — they consume both as anonymous numeric features
    # and the convention is identical in training and inference — but anything
    # geographic must swap them back. Corrected here so the API contract means
    # what it says and every consumer gets real WGS84 coordinates.
    return DistrictOut(
        id=d.id, name=d.name, region=d.region,
        lat=d.shp_lon, lon=d.shp_lat, area_km2=d.shp_area,
        cluster=d.cluster, population=d.population, threshold=d.threshold_75,
    )


@router.get("/districts", response_model=List[DistrictOut], tags=["districts"])
def list_districts(
    region: Optional[str] = Query(None, description="Filter by region name."),
    search: Optional[str] = Query(None, description="Case-insensitive name match."),
    db: Session = Depends(get_db),
):
    """List health districts, ordered by region then name."""
    q = db.query(District)
    if region:
        q = q.filter(District.region == region)
    if search:
        q = q.filter(District.name.ilike(f"%{search}%"))
    return [_to_out(d) for d in q.order_by(District.region, District.name).all()]


@router.get("/districts/{name}", response_model=DistrictOut, tags=["districts"])
def get_district(name: str, db: Session = Depends(get_db)):
    """One district by exact name."""
    d = db.query(District).filter(District.name == name).first()
    if d is None:
        raise HTTPException(404, f"Unknown district: {name}")
    return _to_out(d)
