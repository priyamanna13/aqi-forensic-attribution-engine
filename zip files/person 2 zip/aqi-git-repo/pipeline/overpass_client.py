"""
Overpass API client for runtime pollution source discovery.

Queries OpenStreetMap via the Overpass API for tagged features within a city
bounding box that are known pollution contributors:
  - landuse=industrial        → industrial sources
  - building=construction     → active construction sites
  - highway=trunk|primary|secondary (lanes>=4) → major traffic corridors
  - amenity=waste_disposal / landuse=landfill   → waste burning sites

Each discovered feature is returned as a normalised source dict with GeoJSON
geometry, ready for downstream attribution scoring and database ingestion.
"""

import logging
import time
from typing import Any, Optional
import yaml
import requests

try:
    from shapely.geometry import shape as shapely_shape
    from geoalchemy2.elements import WKTElement
except ImportError:
    shapely_shape = None
    WKTElement = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

logger = logging.getLogger(__name__)

# Overpass QL query templates. {bbox} is replaced at runtime with
# "south,west,north,east" (the format Overpass expects).
OVERPASS_QUERIES: dict[str, str] = {
    "industrial": '''[out:json][timeout:30];
        (
          way["landuse"="industrial"]({bbox});
          relation["landuse"="industrial"]({bbox});
        );
        out center geom;''',
    "construction": '''[out:json][timeout:30];
        (
          way["building"="construction"]({bbox});
          node["construction"="yes"]({bbox});
        );
        out center geom;''',
    "traffic": '''[out:json][timeout:30];
        (
          way["highway"~"trunk|primary|secondary"]["lanes">=4]({bbox});
        );
        out geom;''',
    "waste_burning": '''[out:json][timeout:30];
        (
          node["amenity"="waste_disposal"]({bbox});
          way["landuse"="landfill"]({bbox});
        );
        out center geom;''',
}

# Human-readable descriptions per source type.
_DESCRIPTIONS: dict[str, str] = {
    "industrial": "Industrial zone identified from OSM landuse tagging",
    "construction": "Active construction site identified from OSM building/construction tagging",
    "traffic": "Major traffic corridor (>=4 lanes) identified from OSM highway tagging",
    "waste_burning": "Waste disposal / landfill site identified from OSM tagging",
}

# Rate-limit delay (seconds) between consecutive Overpass requests.
_RATE_LIMIT_DELAY: int = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_geojson_geometry(element: dict) -> dict:
    """Convert an Overpass element into a GeoJSON geometry dict."""
    # Case 1: center key (produced by `out center`)
    if "center" in element:
        return {
            "type": "Point",
            "coordinates": [element["center"]["lon"], element["center"]["lat"]],
        }

    # Case 2: plain node
    if element.get("type") == "node" and "lon" in element and "lat" in element:
        return {
            "type": "Point",
            "coordinates": [element["lon"], element["lat"]],
        }

    # Case 3: geometry list (ways / relations with `out geom`)
    if "geometry" in element and isinstance(element["geometry"], list):
        coords = [
            [pt["lon"], pt["lat"]]
            for pt in element["geometry"]
            if "lon" in pt and "lat" in pt
        ]
        if len(coords) < 2:
            if coords:
                return {"type": "Point", "coordinates": coords[0]}
            return {"type": "GeometryCollection", "geometries": []}

        # Closed ring -> Polygon, open -> LineString
        if coords[0] == coords[-1] and len(coords) >= 4:
            return {"type": "Polygon", "coordinates": [coords]}
        return {"type": "LineString", "coordinates": coords}

    # Fallback
    return {"type": "GeometryCollection", "geometries": []}


def _element_name(element: dict, source_type: str) -> str:
    """Return a human-readable name for an Overpass element."""
    tags = element.get("tags", {})
    if tags.get("name"):
        return tags["name"]
    osm_type = element.get("type", "unknown")
    osm_id = element.get("id", 0)
    return f"{source_type}_{osm_type}_{osm_id}"


def _osm_id_string(element: dict) -> str:
    """Build a canonical `type/id` string for deduplication."""
    return f"{element.get('type', 'unknown')}/{element.get('id', 0)}"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class OverpassSourceDiscovery:
    """Discover pollution-relevant features from OpenStreetMap."""

    def __init__(self, city_config: Optional[dict] = None) -> None:
        if city_config is None:
            try:
                with open("city_config.yml", "r", encoding="utf-8") as f:
                    city_config = yaml.safe_load(f)
            except Exception as e:
                logger.warning("Could not load city_config.yml, falling back to Pune default bbox: %s", e)
                city_config = {
                    "city": {
                        "bbox": {
                            "south": 18.4000,
                            "west": 73.7500,
                            "north": 18.6500,
                            "east": 74.0000
                        }
                    }
                }
        bbox_cfg = city_config["city"]["bbox"]
        self.south: float = float(bbox_cfg["south"])
        self.west: float = float(bbox_cfg["west"])
        self.north: float = float(bbox_cfg["north"])
        self.east: float = float(bbox_cfg["east"])
        logger.info(
            "OverpassSourceDiscovery initialised - bbox: S=%.4f W=%.4f N=%.4f E=%.4f",
            self.south, self.west, self.north, self.east,
        )

    def _format_bbox(self) -> str:
        """Return the bounding box as 'south,west,north,east'."""
        return f"{self.south},{self.west},{self.north},{self.east}"

    def _run_query(self, query_type: str) -> list[dict]:
        """Execute a single Overpass query and normalise the results."""
        template = OVERPASS_QUERIES.get(query_type)
        if template is None:
            logger.warning("Unknown Overpass query type: %s", query_type)
            return []

        query = template.replace("{bbox}", self._format_bbox())
        logger.debug("Running Overpass query [%s] ...", query_type)

        try:
            response = requests.post(
                OVERPASS_URL,
                data=query,
                headers={"User-Agent": "AQI-Attribution-Engine/3.1.0"},
                timeout=45,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.warning("Overpass query '%s' failed: %s", query_type, exc)
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning("Overpass query '%s' returned non-JSON response", query_type)
            return []

        elements = data.get("elements", [])
        logger.info("Overpass query [%s] returned %d element(s)", query_type, len(elements))

        sources: list[dict] = []
        for element in elements:
            source = {
                "name": _element_name(element, query_type),
                "osm_id": _osm_id_string(element),
                "source_type": query_type,
                "source_origin": "osm",
                "geometry": _build_geojson_geometry(element),
                "description": _DESCRIPTIONS.get(
                    query_type,
                    f"Pollution source ({query_type}) from OSM",
                ),
            }
            sources.append(source)

        return sources

    def discover_sources(self, session: Optional[Any] = None) -> Any:
        """Run all Overpass queries, deduplicate, and optionally persist to DB.

        If a database session is provided, UPSERTs the sources into PollutionSource
        and returns the total count of discovered sources.
        If session is None, returns the list of discovered source dictionaries.
        """
        all_sources: list[dict] = []
        query_types = list(OVERPASS_QUERIES.keys())

        for idx, qtype in enumerate(query_types):
            results = self._run_query(qtype)
            all_sources.extend(results)
            if idx < len(query_types) - 1:
                logger.debug("Rate-limit pause (%ds) before next query ...", _RATE_LIMIT_DELAY)
                time.sleep(_RATE_LIMIT_DELAY)

        seen: set[str] = set()
        unique_sources: list[dict] = []
        for source in all_sources:
            osm_id = source["osm_id"]
            if osm_id not in seen:
                seen.add(osm_id)
                unique_sources.append(source)

        logger.info(
            "Discovered %d unique source(s) across %d query type(s) (%d before dedup)",
            len(unique_sources), len(query_types), len(all_sources),
        )

        if session is not None and shapely_shape is not None and WKTElement is not None:
            try:
                from db.models import PollutionSource
                for src in unique_sources:
                    osm_id_val = src["osm_id"]
                    existing = session.query(PollutionSource).filter_by(osm_id=osm_id_val).first()
                    geom_val = WKTElement(shapely_shape(src["geometry"]).wkt, srid=4326)
                    if existing:
                        existing.name = src["name"]
                        existing.type = src["source_type"]
                        existing.geom = geom_val
                        existing.description = src["description"]
                    else:
                        new_src = PollutionSource(
                            name=src["name"],
                            type=src["source_type"],
                            geom=geom_val,
                            osm_id=osm_id_val,
                            source_origin="osm",
                            description=src["description"],
                        )
                        session.add(new_src)
                session.commit()
                logger.info("Successfully persisted %d OSM sources to database.", len(unique_sources))
            except Exception as e:
                logger.error("Error persisting OSM sources to database: %s", e)
                session.rollback()
            return len(unique_sources)

        return unique_sources


def discover_and_format(city_config: dict) -> list[dict]:
    """One-shot helper: discover OSM pollution sources for a city."""
    discovery = OverpassSourceDiscovery(city_config)
    return discovery.discover_sources()
