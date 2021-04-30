"""
Support for interaction with Frontier Silicon Devices
For example internet radios from: Medion, Hama, Auna, ...
"""
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import logging
import traceback
from lxml import objectify


class FSAPI(object):

    DEFAULT_TIMEOUT_IN_SECONDS = 1

    PLAY_STATES = {
        0: 'stopped',
        1: 'unknown',
        2: 'playing',
        3: 'paused',
    }

    def __init__(self, fsapi_device_url, pin, timeout=DEFAULT_TIMEOUT_IN_SECONDS):
        self.pin = pin
        self.sid = None
        self.webfsapi = None
        self.fsapi_device_url = fsapi_device_url
        self.timeout = timeout

        self.session = requests.Session()
        retry = Retry(connect=3, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self.webfsapi = self.get_fsapi_endpoint()
        self.sid = self.create_session()

    def get_fsapi_endpoint(self):
        endpoint = self.session.get(self.fsapi_device_url, timeout=self.timeout)
        doc = objectify.fromstring(endpoint.content)
        return doc.webfsapi.text

    def create_session(self):
        doc = self.call('CREATE_SESSION')
        return doc.sessionId.text

    def call(self, path, extra=None):
        """Execute a frontier silicon API call."""
        try:
            if not self.webfsapi:
                raise Exception('No server found')

            if type(extra) is not dict:
                extra = dict()

            params = dict(
                pin=self.pin,
                sid=self.sid,
            )

            params.update(**extra)

            result = self.session.get('%s/%s' % (self.webfsapi, path), params=params, timeout=self.timeout)
            if result.status_code == 404:
                return None

            return objectify.fromstring(result.content)
        except Exception as e:
            logging.error('FSAPI Exception: ' + traceback.format_exc())

        return None

    def __del__(self):
        self.call('DELETE_SESSION')

    # Handlers

    def handle_get(self, item):
        return self.call('GET/{}'.format(item))

    def handle_set(self, item, value):
        doc = self.call('SET/{}'.format(item), dict(value=value))
        if doc is None:
            return None

        return doc.status == 'FS_OK'

    def handle_text(self, item):
        doc = self.handle_get(item)
        if doc is None:
            return None

        return doc.value.c8_array.text or None

    def handle_int(self, item):
        doc = self.handle_get(item)
        if doc is None:
            return None

        return int(doc.value.u8.text)

    # returns an int, assuming the value does not exceed 8 bits
    def handle_long(self, item):
        doc = self.handle_get(item)
        if doc is None:
            return None

        return int(doc.value.u32.text)

    def handle_list(self, item):
        doc = self.call('LIST_GET_NEXT/'+item+'/-1', dict(
            maxItems=100,
        ))

        if doc is None:
            return []

        if not doc.status == 'FS_OK':
            return []

        ret = list()
        for index, item in enumerate(list(doc.iterchildren('item'))):
            temp = dict(band=index)
            for field in list(item.iterchildren()):
                temp[field.get('name')] = list(field.iterchildren()).pop()
            ret.append(temp)

        return ret

    def collect_labels(self, items):
        if items is None:
            return []

        return [str(item['label']) for item in items if item['label']]

    # Properties
    @property
    def play_status(self):
        status = self.handle_int('netRemote.play.status')
        return self.PLAY_STATES.get(status)

    @property
    def play_info_name(self):
        return self.handle_text('netRemote.play.info.name')

    @property
    def play_info_text(self):
        return self.handle_text('netRemote.play.info.text')

    @property
    def play_info_artist(self):
        return self.handle_text('netRemote.play.info.artist')

    @property
    def play_info_album(self):
        return self.handle_text('netRemote.play.info.album')

    @property
    def play_info_graphics(self):
        return self.handle_text('netRemote.play.info.graphicUri')

    @property
    def volume_steps(self):
        return self.handle_int('netRemote.sys.caps.volumeSteps')

    # Read-write

    # 1=Play; 2=Pause; 3=Next (song/station); 4=Previous (song/station)
    def play_control(self, value):
        return self.handle_set('netRemote.play.control', value)

    def play(self):
        return self.play_control(1)

    def pause(self):
        return self.play_control(2)

    def forward(self):
        return self.play_control(3)

    def rewind(self):
        return self.play_control(4)

    # Volume
    def get_volume(self):
        return self.handle_int('netRemote.sys.audio.volume')

    def set_volume(self, value):
        return self.handle_set('netRemote.sys.audio.volume', value)

    volume = property(get_volume, set_volume)

    # Frienldy name
    def get_friendly_name(self):
        return self.handle_text('netRemote.sys.info.friendlyName')

    def set_friendly_name(self, value):
        return self.handle_set('netRemote.sys.info.friendlyName', value)

    friendly_name = property(get_friendly_name, set_friendly_name)

    # Mute
    def get_mute(self):
        return bool(self.handle_int('netRemote.sys.audio.mute'))

    def set_mute(self, value=False):
        return self.handle_set('netRemote.sys.audio.mute', int(value))

    mute = property(get_mute, set_mute)

    # Power
    def get_power(self):
        return bool(self.handle_int('netRemote.sys.power'))

    def set_power(self, value=False):
        return self.handle_set('netRemote.sys.power', int(value))

    power = property(get_power, set_power)

    # Modes
    @property
    def modes(self):
        return self.handle_list('netRemote.sys.caps.validModes')

    @property
    def mode_list(self):
        return self.collect_labels(self.modes)

    def get_mode(self):
        mode = None
        int_mode = self.handle_long('netRemote.sys.mode')
        for temp_mode in self.modes:
            if temp_mode['band'] == int_mode:
                mode = temp_mode['label']

        return str(mode)

    def set_mode(self, value):
        mode = -1
        for temp_mode in self.modes:
            if temp_mode['label'] == value:
                mode = temp_mode['band']

        self.handle_set('netRemote.sys.mode', mode)

    mode = property(get_mode, set_mode)

    # States
    # Disables/Enables navigation state, will automatically get disabled after changing mode (reset)

    def get_state(self):
        return bool(self.handle_int('netRemote.nav.state'))

    def set_state(self, value=True):
        return self.handle_set('netRemote.nav.state', int(value))

    state = property(get_state, set_state)

    # Presets
    @property
    def presets(self):
        return self.handle_list('netRemote.nav.presets')

    # GET preset call does not exist but play.info.name can be matched with the names in the presets list
    def get_preset(self):
        return self.handle_text('netRemote.play.info.name')

    def set_preset(self, value):
        preset = -1
        for temp_preset in self.presets:
            if temp_preset['name'] == value:
                preset = temp_preset['band']

        return self.handle_set('netRemote.nav.action.selectPreset', preset)

    preset = property(get_preset, set_preset)

    def get_position(self):
        return self.handle_long('netRemote.play.position')

    def set_position(self, value):
        return self.handle_set('netRemote.play.position', int(value))

    position = property(get_position, set_position)

    @property
    def duration(self):
        return self.handle_long('netRemote.play.info.duration')

    # Equalizer Presets
    @property
    def eq_presets(self):
        return self.handle_list('netRemote.sys.caps.eqPresets')

    def get_eq_preset(self):
        eq = None
        int_eq = self.handle_int('netRemote.sys.audio.eqPreset')
        for temp_eq in self.eq_presets:
            if temp_eq['band'] == int_eq:
                eq = temp_eq['label']

        return str(eq)

    def set_eq_preset(self, value):
        eq_preset = -1
        for temp_eq_preset in self.eq_presets:
            if temp_eq_preset['label'] == value:
                eq_preset = temp_eq_preset['band']

        return self.handle_set('netRemote.sys.audio.eqPreset', eq_preset)

    eq_preset = property(get_eq_preset, set_eq_preset)

