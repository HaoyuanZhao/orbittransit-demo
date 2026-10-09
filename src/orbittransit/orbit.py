"""Synthetic constellation generation, extracted from the original OrbitTransit implementation.

The TLE designator helper follows Hypatia (MIT); see third_party/Hypatia-LICENSE.
"""

from sgp4.api import Satrec, WGS72, jday
from sgp4.exporter import export_tle
import math
from astropy.constants import G, M_earth, R_earth
import ephem
import networkx as nx

from .models import Satellite, OrbitLinkMap

GRAVITY_MODEL = WGS72
jd, fr = jday(2000, 1, 1, 0, 0, 0)
EPOCH = (jd + fr) - 2433281.5
DRAG_COEFFICIENT = 0.0
ECCENTRICITY = 0.0000001
ARG_PERIGEE_RAD = 0.0
PHASE_DIFF = True
SECONDS_ONE_DAY = 86400.0
mu = G.value * M_earth.value


def generate_tles(
        num_orbits,
        num_sats_per_orbit,
        inclination_deg,
        altitude_m,
        satellite_id=0,
        is_iridium=False,  # Iridium like constellations place orbits on half Earth longitudes
        epoch=EPOCH,
):
    tles = []
    for orbit_index in range(0, num_orbits):
        for sat_index in range(0, num_sats_per_orbit):
            tle_line1, tle_line2 = generate_tle_for_sat(
                satellite_id,
                orbit_index,
                sat_index,
                num_orbits,
                num_sats_per_orbit,
                inclination_deg,
                altitude_m,
                is_iridium,
                epoch,
            )
            tles.append((tle_line1, tle_line2))
            satellite_id += 1

    return tles

def generate_tle_for_sat(
        satellite_id,
        orbit_index,
        sat_index,
        num_orbits,
        num_sats_per_orbit,
        inclination_deg,
        altitude_m,
        is_iridium=False,
        epoch=EPOCH,
):
    sat = Satrec()

    orbit_phasing_shift = orbit_phasing(orbit_index, num_sats_per_orbit)
    mean_anomaly_deg = mean_anomaly_degree(orbit_phasing_shift, sat_index, num_sats_per_orbit)

    period_s = get_orbit_period(altitude_m)
    mean_motion_radian_per_minute = mm_radian_per_minute(period_s)
    _raan_deg = raan_deg(orbit_index, num_orbits, is_iridium)

    sat.sgp4init(
        GRAVITY_MODEL,        # gravity model
        'i',                  # 'a' = old AFSPC mode, 'i' = improved mode
        satellite_id,         # satnum: Satellite number
        epoch,       # days since 1949 December 31 00:00 UT
        DRAG_COEFFICIENT,     # bstar: drag coefficient (1/earth radii)
        0.0,                  # ndot: ballistic coefficient (revs/day)
        0.0,                  # nddot: mean motion 2nd derivative (revs/day^3)
        ECCENTRICITY,         # ecco: eccentricity
        ARG_PERIGEE_RAD,      # argpo: argument of perigee (radians)
        math.radians(inclination_deg),    # inclo: inclination (radians)
        math.radians(mean_anomaly_deg),   # mo: mean anomaly (radians)
        mean_motion_radian_per_minute,    # no_kozai: mean motion (radians/minute)
        math.radians(_raan_deg),          # nodeo: R.A. of ascending node (radians)
    )

    tle_line1, tle_line2 = export_tle(sat)
    tle_line1 = update_tle_international_designator(tle_line1)

    return tle_line1, tle_line2

def orbit_phasing(orbit_index, num_sats_per_orbit):
    """
    Return orbit phasing shift.
    """
    if orbit_index % 2 != 1 or not PHASE_DIFF:
        return 0
    return 360.0 / (num_sats_per_orbit * 2.0)

def mean_anomaly_degree(orbit_phasing_shift, sat_index, num_sats_per_orbit):
    """
    This is the angular position of the satellite in its orbit.
    """
    return orbit_phasing_shift + (sat_index / num_sats_per_orbit * 360.0)

def raan_deg(orbit_index, num_orbits, is_iridium=False):
    """
    Right ascension of the ascending node.
    """
    if is_iridium:
        return orbit_index * 180.0 / num_orbits
    else:
        return orbit_index * 360.0 / num_orbits

def update_tle_international_designator(tle_line1):
    """
    We adopt Hypatia's approach to change the international designator to 00000ABC in TLE line 1
    https://github.com/snkas/hypatia/blob/master/satgenpy/satgen/tles/generate_tles_from_scratch.py
    """
    tle_line1 = tle_line1[:7] + "U 00000ABC " + tle_line1[18:]
    tle_prefix_68_chars = tle_line1[:68]
    # Compute TLE checksum
    s = 0
    for i in range(len(tle_prefix_68_chars)):
        if tle_prefix_68_chars[i].isnumeric():
            s += int(tle_prefix_68_chars[i])
        if tle_prefix_68_chars[i] == "-":
            s += 1
    checksum = s % 10
    return tle_line1[:68] + str(checksum)

def mm_rev_per_day(period_s):
    """
    Return the mean motion in the unit cycle per day.
    """
    return SECONDS_ONE_DAY / period_s

def mm_radian_per_minute(period_s):
    """
    Conversion information can be found here:
    https://www.translatorscafe.com/unit-converter/en-US/velocity-angular/1-9/radian/second-revolution/day/
    """
    mean_motion_per_day = mm_rev_per_day(period_s)
    return mean_motion_per_day * 60 / 13750.9870831397

def get_orbit_period(altitude_m):
    """
    altitude: the altitude of the satellite in meters
    Return the period of orbit in seconds.
    """
    # a is the length of the major axis in meters
    a = R_earth.value + altitude_m
    return 2 * math.pi * math.sqrt(a ** 3 / mu)


def build_constellation(config, parameters, start_time):
    date = ephem.Date(start_time).datetime()
    jd, fraction = jday(date.year, date.month, date.day, date.hour, date.minute, date.second)
    epoch = jd + fraction - 2433281.5
    tles = generate_tles(config.planes, config.satellites_per_plane,
                         config.inclination_degrees, config.altitude_km * 1000, epoch=epoch)
    return [Satellite(sid, ephem.readtle(f"Synthetic-{sid}", line1, line2),
                      sid // config.satellites_per_plane, sid % config.satellites_per_plane,
                      parameters)
            for sid, (line1, line2) in enumerate(tles)]


def reachable(satellites, point, parameters):
    result = []
    for satellite in satellites:
        satellite.body.compute(point)
        if (math.degrees(satellite.body.alt) > parameters.min_elevation_degrees
                and satellite.body.range < parameters.max_ground_link_km * 1000):
            result.append(satellite)
    return result


def satellite_distance_m(first, second, date):
    """Hypatia's observer/triangle distance calculation (MIT, ETH Zurich)."""
    point = ephem.Observer()
    point.epoch = point.date = date
    point.lat = point.lon = "0"
    point.elevation = 0
    first.compute(point)
    second.compute(point)
    angle = float(ephem.separation(first, second))
    squared = first.range ** 2 + second.range ** 2 - 2 * first.range * second.range * math.cos(angle)
    return math.sqrt(max(0.0, squared))


def build_graph(satellites, constellation, parameters, date):
    """The original intra-plane/cross-plane grid with a distance cutoff."""
    graph = nx.Graph()
    graph.add_nodes_from(satellite.id for satellite in satellites)
    count = constellation.satellites_per_plane
    for satellite in satellites:
        neighbors = [satellite.plane * count + (satellite.slot + 1) % count,
                     ((satellite.plane + 1) % constellation.planes) * count + satellite.slot]
        for other_id in neighbors:
            if satellite_distance_m(satellite.body, satellites[other_id].body, date) <= parameters.max_isl_km * 1000:
                graph.add_edge(satellite.id, other_id)
    return graph


def neighboring_paths(satellite, constellation):
    """Same-slot satellites, visited in increasing plane distance."""
    forward, backward = [], []
    count = constellation.satellites_per_plane
    for distance in range(1, constellation.planes // 2 + 1):
        forward.append(((satellite.plane + distance) % constellation.planes) * count + satellite.slot)
        backward.append(((satellite.plane - distance) % constellation.planes) * count + satellite.slot)
        yield tuple([satellite.id] + forward)
        if backward[-1] != forward[-1]:
            yield tuple([satellite.id] + backward)


def build_contact_map(satellites, stations, constellation, parameters, date):
    contacts = OrbitLinkMap(date)
    for plane in range(constellation.planes):
        satellite = satellites[plane * constellation.satellites_per_plane]
        minutes = math.ceil(1440 / satellite.body._n)
        for minute in range(minutes):
            visible = []
            for station in stations:
                station.point.date = date + minute / 1440
                if reachable([satellite], station.point, parameters):
                    visible.append(station.id)
            contacts.contacts[plane].append(visible)
    for station in stations:
        station.point.date = date
    return contacts
