# -*- encoding: utf-8 -*-
"""
Hafas2GTFS

Usage:
  hafas2gtfs.py <input_dir> <output_dir> [--mapping=<mp>] [--projection=<proj>]
  hafas2gtfs.py -h | --help
  hafas2gtfs.py --version

Options:
  -h --help            Show this screen.
  --version            Show version.
  --mapping=<mp>       Map standard filenames to others in k:v,k:v format
  --projection=<proj>  If coordinates use projection, give projection string

"""
import os
import errno
from datetime import datetime, timedelta
from collections import defaultdict

import unicodecsv
from bitstring import Bits
from pyproj import Proj


GTFS_FILES = {
    'agency.txt': ('agency_id', 'agency_name', 'agency_url', 'agency_timezone', 'agency_lang', 'agency_phone'),
    'routes.txt': ('route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_desc', 'route_type', 'route_url', 'route_color', 'route_text_color'),
    'trips.txt': ('route_id', 'service_id', 'trip_id', 'trip_headsign', 'trip_short_name', 'direction_id', 'block_id', 'shape_id'),
    'stop_times.txt': ('trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence', 'stop_headsign', 'pickup_type', 'drop_off_type', 'shape_dist_traveled'),
    'stops.txt': ('stop_id', 'stop_code', 'stop_name', 'stop_desc', 'stop_lat', 'stop_lon', 'zone_id', 'stop_url', 'location_type', 'parent_station'),
    'calendar.txt': ('service_id', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'start_date', 'end_date'),
    'calendar_dates.txt': ('service_id', 'date', 'exception_type')
}

"""
    0 - Tram, Streetcar, Light rail. Any light rail or street level system within a metropolitan area.
    1 - Subway, Metro. Any underground rail system within a metropolitan area.
    2 - Rail. Used for intercity or long-distance travel.
    3 - Bus. Used for short- and long-distance bus routes.
    4 - Ferry. Used for short- and long-distance boat service.
    5 - Cable car. Used for street-level cable cars where the cable runs beneath the car.
    6 - Gondola, Suspended cable car. Typically used for aerial cable cars where the car is suspended from the cable.
    7 - Funicular. Any rail system designed for steep inclines.
"""

ROUTE_TYPES = {
    'UUU': 0,
    'BUS': 0,
    'NFB': 0,
    'STR': 0,
    'STA': 0,
    'SBA': 0,
    'ZUG': 0,
    'SCH': 0,
    'ALT': 0,
    'TB': 0,
    'VUU': 0,
    'VBU': 0,
    'VNF': 0,
    'VSR': 0,
    'VSA': 0,
    'VSB': 0,
    'VZU': 0,
    'VSC': 0,
    'VAL': 0
}

projector_utm = Proj(
    proj='utm',
    zone=32,
    ellps='WGS84'
)

projector_gk_cologne = Proj(
    proj='tmerc',
    lat_0=0,
    lon_0=6,
    k=1,
    x_0=2500000,
    y_0=0,
    ellps='bessel',
    towgs84='582,105,414,1.04,0.35,-3.08,8.3',
    units='m'
)


def convert_utm(x, y):
    """ UTM2LatLon """
    lon, lat = projector_utm(x, y, inverse=True)
    return lat, lon


def convert_gk_cologne(x, y):
    """ GK2LatLon """
    lon, lat = projector_gk_cologne(x, y, inverse=True)
    return lat, lon


PROJECTIONS = {
    'utm': convert_utm,
    'gk_cologne': convert_gk_cologne
}


def get_projector(name):
    if name is None:
        return lambda x, y: (y, x)
    if name in PROJECTIONS:
        return PROJECTIONS[name]
    return Proj(name)


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else:
            raise


class Hafas2GTFS(object):
    def __init__(self, hafas_dir, out_dir, mapping=None, projection=None):
        self.hafas_dir = hafas_dir
        self.out_dir = out_dir
        self.mapping = mapping
        self.projector = get_projector(projection)
        self.route_counter = 0
        self.routes = {}
        self.stops = defaultdict(dict)

    def make_gtfs_files(self):
        self.files = {}
        for gtfs_file, columns in GTFS_FILES.items():
            self.files[gtfs_file] = unicodecsv.DictWriter(
                file(os.path.join(self.out_dir, gtfs_file), 'w'),
                columns
            )
            self.files[gtfs_file].writeheader()

    def get_path(self, name):
        return os.path.join(self.hafas_dir, name)

    def get_name(self, name):
        if self.mapping is None:
            return name
        return self.mapping.get(name, name)

    def create(self):
        mkdir_p(self.out_dir)
        self.make_gtfs_files()

        self.parse_eckdaten()
        self.write_agency()

        self.parse_bitfeld()
        self.write_service()
        self.write_service_dates()

        self.parse_bfkoord()
        self.parse_bahnhof()

        self.parse_fplan()

    def write_agency(self):
        self.agency_id = '1'
        self.files['agency.txt'].writerow({
            'agency_id': self.agency_id,
            'agency_name': 'Agency Name',
            'agency_url': '',
            'agency_timezone': '',
            'agency_lang': '',
            'agency_phone': ''
        })
        return self.agency_id

    def write_service(self):
        """
        Writes full service on default ID 0
        and all existing service IDs from bitfield
        `write_service_dates` writes out exceptions
        for the actual service dates
        """

        def write_full_service(service_id):
            self.files['calendar.txt'].writerow({
                'service_id': service_id,
                'monday': '1',
                'tuesday': '1',
                'wednesday': '1',
                'thursday': '1',
                'friday': '1',
                'saturday': '1',
                'sunday': '1',
                'start_date': self.start.strftime('%Y%m%d'),
                'end_date': self.end.strftime('%Y%m%d')
            })

        write_full_service('0')

        for service_id, bitfield in self.services.items():
            write_full_service(str(service_id))

    def write_service_dates(self):
        for service_id, bitfield in self.services.items():
            for i, available in enumerate(bitfield):
                if available:
                    date = (self.start + timedelta(days=i))
                    self.files['calendar_dates.txt'].writerow({
                        'service_id': service_id,
                        'date': date.strftime('%Y%m%d'),
                        'exception_type': 1
                    })

    def write_route(self, meta):
        route_id = meta.get('line_number')
        if route_id is None:
            self.route_counter += 1
            route_id = self.route_counter
        if route_id in self.routes:
            return self.routes[route_id]
        self.routes[route_id] = route_id
        self.files['routes.txt'].writerow({
            'route_id': route_id,
            'agency_id': self.agency_id,
            'route_short_name': route_id,
            'route_long_name': route_id,
            'route_desc': '',
            'route_type': str(ROUTE_TYPES.get(meta['mean_of_transport'], 0)),
            'route_url': '',
            'route_color': '',
            'route_text_color': ''
        })
        return route_id

    def write_trip(self, route_id, meta):
        service_id = str(meta.get('bitfield_number', 0))
        self.files['trips.txt'].writerow({
            'route_id': route_id,
            'service_id': service_id,
            'trip_id': meta['service_number'],
            'trip_headsign': '',
            'trip_short_name': '',
            'direction_id': meta.get('direction', '0'),
            'block_id': '',
            'shape_id': ''
        })
        return meta['service_number']

    def get_gtfs_time(self, time):
        if time is None:
            return None
        time = list(time)
        if len(time) == 2:
            time = time + ['00']
        time = [str(t).zfill(2) for t in time]
        return ':'.join(time)

    def write_stop(self, stop_line):
        stop_id = stop_line['stop_id']
        stop_data = self.stops[stop_id]
        if stop_data.get('done', False):
            return stop_id
        self.files['stops.txt'].writerow({
            'stop_id': stop_id,
            'stop_code': stop_id,
            'stop_name': stop_data['name'],
            'stop_desc': '',
            'stop_lat': str(stop_data['lat']),
            'stop_lon': str(stop_data['lon']),
            'zone_id': None,
            'stop_url': '',
            'location_type': '0',  # FIXME
            'parent_station': None
        })
        stop_data['done'] = True
        return stop_id

    def write_stop_time(self, trip_id, stop_sequence, stop_line):
        stop_id = self.write_stop(stop_line)

        arrival_time = self.get_gtfs_time(stop_line['arrival_time'])
        departure_time = self.get_gtfs_time(stop_line['departure_time'])

        if not arrival_time and departure_time:
            arrival_time = departure_time
        elif not departure_time and arrival_time:
            departure_time = arrival_time

        self.files['stop_times.txt'].writerow({
            'trip_id': trip_id,
            'arrival_time': arrival_time,
            'departure_time': departure_time,
            'stop_id': stop_id,
            'stop_sequence': stop_sequence,
            'stop_headsign': '',
            'pickup_type': '0',
            'drop_off_type': '0',
            'shape_dist_traveled': '0'
        })

    def parse_eckdaten(self):
        contents = file(self.get_path(self.get_name('eckdaten'))).read()
        data = contents.splitlines()
        self.start = datetime.strptime(data[0], '%d.%m.%Y')
        self.end = datetime.strptime(data[1], '%d.%m.%Y')
        self.name = data[1]

    def parse_bitfeld(self):
        self.services = {}
        day_range = (self.start - self.end).days + 1
        for line in file(self.get_path(self.get_name('bitfeld'))):
            line = line.decode('latin1')
            service_id = int(line[:6])
            # "For technical reasons 2 bits are inserted directly
            # before the first day of the start of the timetable period
            # and two bits directly after the last day at the end of the
            # timetable period."
            self.services[service_id] = Bits(hex=line[6:])[2:2 + day_range]

    def parse_bfkoord(self):

        for line in file(self.get_path(self.get_name('bfkoord'))):
            line = line.decode('latin1')
            """
0000001 2567526.00 5644934.00 KÖLN                     Heumarkt
            """
            stop_id = int(line[:7].strip())
            x = float(line[8:18].strip())
            y = float(line[19:29].strip())
            lat, lon = self.projector(x, y)
            self.stops[stop_id].update({
                'lat': lat,
                'lon': lon
            })

    def parse_bahnhof(self):
        for line in file(self.get_path(self.get_name('bahnhof'))):
            line = line.decode('latin1')
            """
0000001 VRS Köln Heumarkt
            """
            stop_id = int(line[:7].strip())
            trans_authority = line[8:11]
            name = line[12:].strip()
            self.stops[stop_id].update({
                'name': name,
                'authority': trans_authority
            })

    def parse_fplan(self):
        state = 'meta'
        meta = {}
        for line in file(self.get_path(self.get_name('fplan'))):
            line = line.decode('latin1')
            if line.startswith('%'):
                continue
            if line.startswith('*'):
                if not state == 'meta':
                    meta = {}
                state = 'meta'
                meta.update(self.parse_fplan_meta(line))
            else:
                if not state == 'data':
                    stop_sequence = 0
                    route_id = self.write_route(meta)
                    trip_id = self.write_trip(route_id, meta)
                    state = 'data'
                stop_sequence += 1
                stop_line_info = self.parse_schedule(line)
                self.write_stop_time(trip_id, stop_sequence, stop_line_info)

    def parse_schedule(self, line):
        """
0000669 Refrath                   0635
        """
        return {
            'stop_id': int(line[:7]),
            'stop_name': line[8:29].strip(),
            'arrival_time': self.parse_time(line[29:33]),
            'departure_time': self.parse_time(line[34:38])
        }

    def parse_time(self, time_str):
        time_str = time_str.strip()
        if not time_str:
            return None
        # TODO: include seconds if present
        return (int(time_str[0:2]), int(time_str[2:4]))

    def parse_fplan_meta(self, line):
        if hasattr(self, 'parse_fplan_meta_%s' % line[1]):
            return getattr(self, 'parse_fplan_meta_%s' % line[1])(line)
        return {}

    def parse_fplan_meta_Z(self, line):
        return {
            'service_number': int(line[3:8]),
            'administration': line[9:15],
            'number_intervals': line[22:25],
            'time_offset': line[26:29]
        }

    def parse_fplan_meta_G(self, line):
        return {
            'mean_of_transport': line[3:6].strip()
        }

    def parse_fplan_meta_A(self, line):
        attribute_code = line[3:5]
        if attribute_code == 'VE':
            return {
                'start_index': line[6:13],
                'end_index': line[14:21],
                'bitfield_number': int(line[22:28]),
            }
        return {}

    def parse_fplan_meta_I(self, line):
        return {}

    def parse_fplan_meta_L(self, line):
        return {
            'line_number': line[3:11].strip()
        }

    def parse_fplan_meta_R(self, line):
        return {
            'direction': line[3:4].strip()
        }


def main(hafas_dir, out_dir, options=None):
    if options is None:
        options = {}
    config = {}
    if options.get('--mapping'):
        config['mapping'] = dict([o.split(':') for o in options.get(
                                 '--mapping').split(',')])
    config['projection'] = options.get('--projection')
    h2g = Hafas2GTFS(hafas_dir, out_dir, **config)
    h2g.create()

if __name__ == '__main__':
    from docopt import docopt

    arguments = docopt(__doc__, version='Hafas2GTFS 0.0.1')
    main(arguments['<input_dir>'], arguments['<output_dir>'], options=arguments)
