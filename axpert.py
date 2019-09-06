import os

from time import sleep
from json import dumps as json_dumps
from crc16 import crc16xmodem
from struct import pack
from threading import Thread


def clean_val(val):
    if not val or val == 'NA':
        return 0
    else:
        return val


def typer(frmt):
    types = {'s': str, 'f': float, 'd': int}
    for frm, type_fnx in types.items():
        if frm in frmt:
            return lambda txt: type_fnx(frmt % type_fnx(clean_val(txt)))

    return lambda txt: txt % frmt


to_float = typer('%.2f')
to_int = typer('%d')
to_str = typer('%s')


class AxpertProtocol(object):

    SOLAR_CHARGING = 'solar_charging'
    AC_CHARGING = 'ac_charging'

    STATUS_STRUCTURE = (
        ('grid_volt', to_float), ('grid_freq', to_float),
        ('ac_volt', to_float), ('ac_freq', to_float),
        ('ac_va', to_int), ('ac_watt', to_int),
        ('load_percent', to_int), ('bus_volt', to_int),
        ('batt_volt', to_float), ('batt_charge_amps', to_int),
        ('batt_capacity', to_int), ('temp', to_int),
        ('pv_amps', to_int), ('pv_volts', to_float),
        ('batt_volt_scc', to_float), ('batt_discharge_amps', to_int),
        ('raw_status', to_str),
        ('mask_b', to_str), ('mask_c', to_str),
        ('pv_watts', to_int), ('mask_d', to_str)
    )

    def parse_device_status(self, raw_status):
        if not raw_status                           \
                or not isinstance(raw_status, str)  \
                or len(raw_status) < 8:
            return {}

        charge_sources = {0b101: self.AC_CHARGING, 0b110: self.SOLAR_CHARGING}
        data = int(raw_status.replace("b", '').replace("'", ''), 2)

        return {
            'charge_source': [
                source for mask, source in charge_sources.items()
                if (mask & data) == mask
            ],
            'batt_volt_to_steady': bool(8 & data),
            'load_status': bool(16 & data),
            'ssc_firmware_updated': bool(32 & data),
            'configuration_changed': bool(64 & data),
            'sbu_priority_version': bool(128 & data)
        }

    def status_json_formatter(self, raw, serialize=True):
        if not raw:
            return None

        # Ignore initial '(' and end 5 byte split
        raw_tokens = raw[1:-5].split(b' ')
        data = {
            label: formatter(token)
            for (label, formatter), token
            in zip(self.STATUS_STRUCTURE, raw_tokens)
        }

        struct = {
            **data,
            **self.parse_device_status(data.get('raw_status', '00000000'))
        }
        return json_dumps(struct) if serialize else struct


class BaseAxpertInverter(object):

    MAX_RETRIES = 10

    def __init__(self, port='/dev/hidraw0', raw=False):
        self.port = port
        self.protocol = AxpertProtocol()
        self.raw = raw
        self.stats = None
        self.stop = False

    def _conn(self):
        try:
            self.hid = os.open(self.port,  os.O_RDWR | os.O_NONBLOCK)
            sleep(1)
            return self.hid
        except Exception:
            self._reset_port()

    def _reset_port(self):
        if self.hid >= 0:
            os.close(self.hid)
        self._conn()

    def __enter__(self):
        for _ in range(self.MAX_RETRIES):
            hid = self._conn()
            if hid is not None:
                return self
            sleep(1)
        raise RuntimeError('Could not connect to hidraw')

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop = True
        sleep(1)
        os.close(self.hid)

    def _stats_req(self):
        encoded_cmd = 'QPIGS'
        checksum = crc16xmodem(str.encode(encoded_cmd))
        return bytes(encoded_cmd, 'utf-8') + pack('>H', checksum) + b'\r'

    def get_stats(self):
        for retry in range(self.MAX_RETRIES):
            try:
                os.write(self.hid, self._stats_req())
                sleep(1)
                response = b''
                while True:
                    chunk = os.read(self.hid, 8)
                    if not chunk or b'\r' in chunk:
                        break
                    response += chunk
                res = (
                    self.protocol.status_json_formatter(response)
                    if not self.raw else response
                )
                if res:
                    return res
            except Exception as e:
                sleep(0.2)
                if retry in [3, 6, 9]:
                    self._reset_port()


class AxpertInverter(BaseAxpertInverter):

    def _conn(self):
        try:
            self.hid = os.open(self.port, os.O_RDWR | os.O_NONBLOCK)
            sleep(1)
            Thread(target=self._read_stats).start()
            return self.hid
        except Exception:
            self._reset_port()

    def _read_stats(self):
        while True and not self.stop:
            try:
                os.write(self.hid, self._stats_req())
                sleep(1)
                response = b''
                while True:
                    chunk = os.read(self.hid, 8)
                    if not chunk or b'\r' in chunk:
                        break
                    response += chunk
                stats = (
                    self.protocol.status_json_formatter(response)
                    if not self.raw else response
                )
                if stats:
                    self.stats = stats
            except Exception:
                pass

    def get_stats(self, block=False):
        if self.stats:
            return self.stats

        elif block:
            for _ in range(self.MAX_RETRIES):
                sleep(1)
                if self.stats:
                    return self.stats
            self.stop = True
            raise RuntimeError('Could not connect to HID')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--base', action='store_true')
    args = parser.parse_args()
    mode = 'normal' if not args.base else 'base'

    if mode is 'base':
        with BaseAxpertInverter() as axpert:
            print(axpert.get_stats())

    else:
        with AxpertInverter() as axpert:
            # Blocking (connection + first call)
            print(axpert.get_stats(block=True))

            for _ in range(300):
                # Non blocking, internal refresh rate of 1 HZ
                print(axpert.get_stats())
                sleep(0.2)
