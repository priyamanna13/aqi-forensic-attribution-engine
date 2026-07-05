"""
Overpass API client for runtime pollution source discovery.

Queries OpenStreetMap via the Overpass API for tagged features within a city
bounding box that are known pollution contributors:
  - landuse=industrial        → industrial sources
  - building=construction     → active construction sites
  - highway=trunk|primary|secondary (lanes>=4) → major traffic corridors
  - amenity=waste_disposal / landuse=landfill   → waste burning sites

Each discovered feature is returned as a normalised source dict with GeoJSON
geometry, ready for downstream attribution scoring.
"""

import logging
import time
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

logger = logging.getLogger(__name__)

# Overpass QL query templates.  {bbox} is replaced at runtime with
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
    "traffic": "Major traffic corridor (≥4 lanes) identified from OSM highway tagging",
    "waste_burning": "Waste disposal / landfill site identified from OSM tagging",
}

# Rate-limit delay (seconds) between consecutive Overpass requests.
_RATE_LIMIT_DELAY: int = 5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_geojson_geometry(element: dict) -> dict:
    """Convert an Overpass element into a GeoJSON geometry dict.

    Strategy:
      1. If the element has a ``center`` key → Point.
      2. If the element type is ``node`` → Point from ``lon``/``lat``.
      3. If the element has a ``geometry`` list:
         a. If the first and last coordinates match → Polygon.
         b. Otherwise → LineString.
      4. Fallback → empty GeometryCollection.

    Args:
        element: A single element dict from the Overpass ``elements`` array.

    Returns:
        A GeoJSON-compliant geometry dictionary.
    """
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
            # Degenerate – treat as point if we have exactly one coordinate
            if coords:
                return {"type": "Point", "coordinates": coords[0]}
            return {"type": "GeometryCollection", "geometries": []}

        # Closed ring → Polygon, open → LineString
        if coords[0] == coords[-1] and len(coords) >= 4:
            return {"type": "Polygon", "coordinates": [coords]}
        return {"type": "LineString", "coordinates": coords}

    # Fallback
    return {"type": "GeometryCollection", "geometries": []}


def _element_name(element: dict, source_type: str) -> str:
    """Return a human-readable name for an Overpass element.

    Uses the OSM ``name`` tag when available, otherwise generates an
    automatic label from the source type and OSM id.

    Args:
        element: Overpass element dict.
        source_type: One of the keys in ``OVERPASS_QUERIES``.

    Returns:
        A descriptive string name.
    """
    tags = element.get("tags", {})
    if tags.get("name"):
        return tags["name"]
    osm_type = element.get("type", "unknown")
    osm_id = element.get("id", 0)
    return f"{source_type}_{osm_type}_{osm_id}"


def _osm_id_string(element: dict) -> str:
    """Build a canonical ``type/id`` string for deduplication.

    Args:
        element: Overpass element dict.

    Returns:
        String like ``'way/123456'``.
    """
    return f"{element.get('type', 'unknown')}/{element.get('id', 0)}"


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class OverpassSourceDiscovery:
    """Discover pollution-relevant features from OpenStreetMap.

    Typical usage::

        discovery = OverpassSourceDiscovery(city_config)
        sources = discovery.discover_sources()

    Args:
        city_config: Configuration dictionary that must contain
            ``city_config['city']['bbox']`` with keys
            ``south``, ``west``, ``north``, ``east`` (floats).
    """

    def __init__(self, city_config: dict) -> None:
        bbox_cfg = city_config["city"]["bbox"]
        self.south: float = float(bbox_cfg["south"])
        self.west: float = float(bbox_cfg["west"])
        self.north: float = float(bbox_cfg["north"])
        self.east: float = float(bbox_cfg["east"])
        logger.info(
            "OverpassSourceDiscovery initialised – bbox: "
            "S=%.4f W=%.4f N=%.4f E=%.4f",
            self.south, self.west, self.north, self.east,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_bbox(self) -> str:
        """Return the bounding box as ``'south,west,north,east'``.

        This is the coordinate order expected by Overpass QL ``({bbox})``
        substitution.

        Returns:
            Comma-separated bbox string.
        """
        return f"{self.south},{self.west},{self.north},{self.east}"

    def _run_query(self, query_type: str) -> list[dict]:
        """Execute a single Overpass query and normalise the results.

        Args:
            query_type: One of ``'industrial'``, ``'construction'``,
                ``'traffic'``, or ``'waste_burning'``.

        Returns:
            A list of normalised source dictionaries.  Returns an empty
            list if the query type is unknown or if a network error occurs.
        """
        template = OVERPASS_QUERIES.get(query_type)
        if template is None:
            logger.warning("Unknown Overpass query type: %s", query_type)
            return []

        query = template.replace("{bbox}", self._format_bbox())
        logger.debug("Running Overpass query [%s] …", query_type)

        try:
            response = requests.post(
                OVERPASS_URL,
                data=query,
                headers={"User-Agent": "AQI-Attribution-Engine/3.1.0"},
                timeout=45,
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "Overpass query '%s' failed: %s", query_type, exc,
            )
            return []

        try:
            data = response.json()
        except ValueError:
            logger.warning(
                "Overpass query '%s' returned non-JSON response", query_type,
            )
            return []

        elements = data.get("elements", [])
        logger.info(
            "Overpass query [%s] returned %d element(s)",
            query_type, len(elements),
        )

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def discover_sources(self) -> list[dict]:
        """Run all Overpass queries and return deduplicated sources.

        Queries are executed sequentially with a 5-second delay between
        each to respect the Overpass API rate limit (≈2 requests / 10 s).

        Returns:
            Combined, deduplicated list of source dictionaries.
        """
        all_sources: list[dict] = []
        query_types = list(OVERPASS_QUERIES.keys())

        for idx, qtype in enumerate(query_types):
            results = self._run_query(qtype)
            all_sources.extend(results)

            # Rate-limit: sleep between queries (skip after the last one)
            if idx < len(query_types) - 1:
                logger.debug(
                    "Rate-limit pause (%ds) before next query …",
                    _RATE_LIMIT_DELAY,
                )
                time.sleep(_RATE_LIMIT_DELAY)

        # Deduplicate by osm_id, keeping the first occurrence.
        seen: set[str] = set()
        unique_sources: list[dict] = []
        for source in all_sources:
            osm_id = source["osm_id"]
            if osm_id not in seen:
                seen.add(osm_id)
                unique_sources.append(source)

        logger.info(
            "Discovered %d unique source(s) across %d query type(s) "
            "(%d before dedup)",
            len(unique_sources), len(query_types), len(all_sources),
        )
        return unique_sources


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def discover_and_format(city_config: dict) -> list[dict]:
    """One-shot helper: discover OSM pollution sources for a city.

    Creates an :class:`OverpassSourceDiscovery` instance and immediately
    runs all queries.

    Args:
        city_config: City configuration dict (see
            :class:`OverpassSourceDiscovery` for the expected shape).

    Returns:
        List of normalised source dictionaries.
    """
    discovery = OverpassSourceDiscovery(city_config)
    return discovery.discover_sources()
