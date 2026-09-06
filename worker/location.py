"""Operator-provided approximate site location. No IP lookup or GPS tracking."""
import math


def location_from_args(args):
    site = getattr(args, 'site', None)
    region = getattr(args, 'region', None)
    latitude = getattr(args, 'latitude', None)
    longitude = getattr(args, 'longitude', None)
    if all(value is None for value in (site, region, latitude, longitude)):
        return None
    if not site or not site.strip() or latitude is None or longitude is None:
        raise ValueError('Location requires --site, --latitude and --longitude together')
    if len(site.strip()) > 200 or (region is not None and not 1 <= len(region.strip()) <= 200):
        raise ValueError('Site and region must contain 1–200 characters')
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError('Latitude must be between -90 and 90')
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError('Longitude must be between -180 and 180')
    return {'site': site.strip(), 'region': region.strip() if region else None,
            'latitude': latitude, 'longitude': longitude}
