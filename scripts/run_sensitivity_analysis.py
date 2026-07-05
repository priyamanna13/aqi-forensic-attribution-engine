"""Automated Sensitivity Analysis Test Runner (Phase 3).

Perturbs wind direction and wind speed (which alters Pasquill stability
and plume half-angle) to demonstrate the robustness of the spatial ranker
and confidence scoring model. Outputs a Markdown metrics table for the judges.
"""
import copy
from pprint import pprint

from app.demo_scenarios import get_scenario
from app.pasquill import classify_stability
from app.wind_cone import generate_wind_cone
from app.ranker import rank_candidates


def run_sensitivity():
    # We will use the Shivajinagar scenario (Construction Spike) for the test.
    scenario = get_scenario("Shivajinagar")
    lon, lat = scenario.coordinates
    
    # Base parameters
    base_wind_dir = 290
    base_wind_speed = 14.5
    cloud_cover = 3
    is_daytime = True
    solar_elevation = 30.0
    fingerprint = {"pm10": 1.0}  # Simplified for test
    
    print("## Sensitivity Analysis Results: Wind Direction & Stability Variance\n")
    print("| Perturbation | Wind Dir (°) | Wind Spd (km/h) | Pasquill Class | Cone Angle (°) | Top Candidate | Confidence Score |")
    print("|--------------|--------------|-----------------|----------------|----------------|---------------|------------------|")
    
    # Define 10 perturbation test cases
    test_cases = [
        ("Baseline", 0, 0),
        ("Wind Dir -10°", -10, 0),
        ("Wind Dir +10°", +10, 0),
        ("Wind Dir -20°", -20, 0),
        ("Wind Dir +20°", +20, 0),
        ("Wind Spd -5 (Low)", 0, -5.0),
        ("Wind Spd +5 (High)", 0, +5.0),
        ("Extreme: Dir -20° + Spd -5", -20, -5.0),
        ("Extreme: Dir +20° + Spd +5", +20, +5.0),
        ("Gale Force (Spd +15)", 0, +15.0),
    ]
    
    for label, d_dir, d_spd in test_cases:
        test_dir = (base_wind_dir + d_dir) % 360
        test_spd = max(1.0, base_wind_speed + d_spd)
        
        # 1. Recalculate Pasquill Stability
        pasquill = classify_stability(test_spd, cloud_cover, is_daytime, solar_elevation)
        p_class = pasquill["pasquill_class"]
        
        # 2. Recalculate Wind Cone
        cone = generate_wind_cone(
            origin_lon=lon,
            origin_lat=lat,
            wind_direction_deg=test_dir,
            pasquill_class=p_class,
            station_name="Shivajinagar"
        )
        half_angle = cone["properties"]["half_angle_deg"]
        reach = cone["properties"]["reach_km"]
        
        # 3. Run Ranker
        candidates = copy.deepcopy(scenario.candidates)
        ranked = rank_candidates(
            candidates=candidates,
            station_coords=(lon, lat),
            wind_direction=test_dir,
            half_angle=half_angle,
            max_range_km=reach,
            chemical_fingerprint=fingerprint,
            event_time="08:30"
        )
        
        if not ranked:
            top_name = "None (Out of Cone)"
            score = "0.00"
        else:
            top_name = ranked[0]["name"].split("—")[0].strip()[:20]
            score = f"{ranked[0]['score_breakdown']['confidence_score']:.2f}"
            
        print(f"| {label:25} | {test_dir:12} | {test_spd:15.1f} | {p_class:14} | {half_angle:14.1f} | {top_name:20} | {score:16} |")

if __name__ == "__main__":
    run_sensitivity()
