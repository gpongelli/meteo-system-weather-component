"""MeteoSystem sensor platform."""
import logging
import re
from datetime import timedelta, datetime
from typing import Any, Callable, Dict, List, Tuple, Optional
from aiohttp.client_exceptions import *
from asyncio.exceptions import *

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION

import asyncio
import async_timeout

from bs4 import BeautifulSoup
import aiohttp
from http import HTTPStatus

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_NAME,
    CONF_URL,
    TEMP_CELSIUS,
    PERCENTAGE,
    DEVICE_CLASS_HUMIDITY,
    DEVICE_CLASS_PRESSURE,
    DEVICE_CLASS_TEMPERATURE,
    PRESSURE_HPA,
    SPEED_METERS_PER_SECOND,
    PRECIPITATION_MILLIMETERS_PER_HOUR,
    LENGTH_MILLIMETERS,
    SPEED_KILOMETERS_PER_HOUR,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_utc_time_change
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.typing import (
    ConfigType,
    DiscoveryInfoType,
    HomeAssistantType,
)

from .const import (
    CONF_STATION_NAME,
    CONF_WEATHER_STATIONS,
    DOMAIN,
    ENTITY_LAST_UPDATE,
    ENTITY_TEMP,
    ENTITY_HUMIDITY,
    ENTITY_PERCEIVED_TEMP,
    ENTITY_TEMP_COMMENT,
    ENTITY_PRESSURE,
    ENTITY_WIND,
    ENTITY_WIND_DIRECTION,
    ENTITY_WIND_COMMENT,
    ENTITY_RAIN,
    ENTITY_RAIN_COMMENT,
    ENTITY_RAIN_INTENSITY,
    ENTITY_STATION_STATUS,
)

_LOGGER = logging.getLogger(__name__)

ATTRIBUTION = (
    "Weather data from meteosystem webpage."
)

STATION_SCHEMA = vol.Schema(
    {vol.Required(CONF_STATION_NAME): cv.string}
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_WEATHER_STATIONS): vol.All(cv.ensure_list, [STATION_SCHEMA]),
        vol.Optional(CONF_URL): cv.url,
    }
)


SENSOR_TYPES = {
    ENTITY_STATION_STATUS:    [None, None, None],
    ENTITY_LAST_UPDATE:       [None, None, "mdi:clock-outline"],
    ENTITY_TEMP:              [TEMP_CELSIUS, DEVICE_CLASS_TEMPERATURE, "mdi:thermometer"],
    ENTITY_PERCEIVED_TEMP:    [TEMP_CELSIUS, DEVICE_CLASS_TEMPERATURE, "mdi:thermometer"],
    ENTITY_TEMP_COMMENT:      [None, None, "mdi:thermometer"],
    ENTITY_HUMIDITY:          [PERCENTAGE, DEVICE_CLASS_HUMIDITY, "mdi:water-percent"],
    ENTITY_PRESSURE:          [PRESSURE_HPA, DEVICE_CLASS_PRESSURE, "mdi:gauge"],
    ENTITY_WIND:              [SPEED_KILOMETERS_PER_HOUR, None, "mdi:weather-windy"],
    ENTITY_WIND_DIRECTION:    [None, None, "mdi:compass"],
    ENTITY_WIND_COMMENT:      [None, None, "mdi:weather-windy"],
    ENTITY_RAIN:              [LENGTH_MILLIMETERS, None, "mdi:weather-pouring"],
    ENTITY_RAIN_INTENSITY:    [PRECIPITATION_MILLIMETERS_PER_HOUR, None, "mdi:weather-pouring"],
    ENTITY_RAIN_COMMENT:      [None, None, "mdi:weather-pouring"],
}


async def async_setup_platform(
    hass: HomeAssistantType,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the sensor platform."""

    dev = []
    _station_names = []
    for weather in config[CONF_WEATHER_STATIONS]:
        _station_name = weather.get(CONF_STATION_NAME).lower()
        _station_names.append(_station_name)
        for k, _ in SENSOR_TYPES.items():
            dev.append(MeteoSystemWeatherSensor(_station_name, k))

    _meteo_system_data_fetcher = MeteoSystemFetcher(hass, config[CONF_URL], dev, _station_names)
    await _meteo_system_data_fetcher.fetch_data()
    async_add_entities(dev)


class MeteoSystemFetcher:
    def __init__(self, hass, url: str, dev: List, stations: List):
        self.hass = hass
        self.__url = url
        self.__data = {d.unique_id: d for d in dev}
        self.__stations = stations

    async def fetch_data(self, *_):
        """Get the latest data from url."""
        try:
            _session = async_get_clientsession(self.hass)

            with async_timeout.timeout(15):
                resp = await _session.get(self.__url)
            if resp.status >= HTTPStatus.BAD_REQUEST:
                raise ValueError(f"Status {resp.status} returned.")

            page_content = await resp.text()

        except (ValueError, ServerDisconnectedError, CancelledError, TimeoutError, ClientOSError, ClientConnectorError,
                asyncio.TimeoutError, aiohttp.ClientError) as e:
            _LOGGER.warning(f"{self.__class__.__name__}: {e.__class__.__qualname__} while retrieving data "
                            f"from {self.__url}: {e}")
        else:
            soup = MeteoSystemFetcher.soup_page(page_content)

            station_name = soup.find_all('span', 'testotitolo')

            for station in self.__stations:
                filtered = list(filter(lambda _page_station: MeteoSystemFetcher.filter_station(_page_station, station),
                                       station_name))

                # sometimes filtered array contains nothing
                if filtered:
                    # only one span element matching the input station name
                    await self.work_on_span(filtered[0], station)
        finally:
            async_call_later(self.hass, 3 * 60, self.fetch_data)

    @staticmethod
    def soup_page(html):
        try:
            return BeautifulSoup(html, 'html.parser')
        except Exception as e:
            _LOGGER.exception(f"Error on BeautifulSoup: {str(e)}")

    @staticmethod
    def filter_station(span, station):
        if re.search(station, span.get_text(), re.IGNORECASE):
            return True
        else:
            return False

    async def update_entity(self, _station_name: str, _entity_name: str, _value: Any, _available: bool):
        _d: MeteoSystemWeatherSensor = self.__data[f"{DOMAIN}_{_station_name}_{_entity_name}"]
        _d._available = _available
        if _available:
            _d._state = _value

        if _d.hass:
            _d.async_write_ha_state()

    async def work_on_span(self, tag, station: str):
        _data = {}

        # print(tag.get_text().strip())
        span_elem = tag.find_next_sibling('span', 'valori3').next_sibling()
        # remove text in between

        # last update
        timest = list(map(lambda x: x.get_text(), [span_elem[0], span_elem[-1]]))
        # print(" ".join(timest).strip())
        _data[ENTITY_LAST_UPDATE] = " ".join(timest).strip()

        # temperature
        temp_span = span_elem[0].find_next('span', 'temp')
        _temp = temp_span.get_text().strip()
        _data[ENTITY_TEMP] = float(_temp) if _temp else 0
        # print(f"TEMP: {temp_span.get_text().strip()}")

        # humidity
        umid_span = temp_span.find_next('span', 'temp')
        _umid = umid_span.get_text().strip()
        _data[ENTITY_HUMIDITY] = float(_umid) if _temp else 0
        # print(f"UMID: {umid_span.get_text().strip()}")

        # perceived temp
        perc_span = umid_span.find_next('span', 'scrittine').find_next('span', 'valori2')
        regval = re.search("(?P<temp>[0-9.]*)\\D", perc_span.get_text().strip())
        _perc = regval.group('temp')
        _data[ENTITY_PERCEIVED_TEMP] = float(_perc) if _perc else 0
        # print(f"percepitavalore: {regval.group('temp')}")

        # temp comment
        temp_status = perc_span.find_next('span', 'avvisi')
        _data[ENTITY_TEMP_COMMENT] = temp_status.get_text().strip()
        # print(f"commentotemp: {temp_status.get_text().strip()}")

        # pressure
        pressure = temp_status.find_next('td', 'bordoalto').find_next('span', 'scrittine')
        pressure_text = pressure.get_text().split(':')
        regval = re.search("(?P<press>[0-9.]*)\\D", pressure_text[1].strip())
        _press = regval.group('press')
        _data[ENTITY_PRESSURE] = float(_press) if _press else 0
        # print(f"pressione: {regval.group('press')}")

        # wind
        wind_speed = pressure.find_next('span', 'temp')
        _wind = wind_speed.get_text().strip()
        _data[ENTITY_WIND] = float(_wind) if _wind else 0
        # print(f"velvento: {velvento.get_text().strip()}")

        wind_direction = wind_speed.find_next('span', 'valor2')
        _direct = wind_direction.get_text().strip().split()[1]
        _data[ENTITY_WIND_DIRECTION] = _direct
        # print(f"dirvento: {dirvento.get_text().strip()}")

        wind_status = wind_direction.find_next('span', 'avvisi').find_next('span', 'avvisi')
        _data[ENTITY_WIND_COMMENT] = wind_status.get_text().strip()
        # print(f"commentovento: {commentovento.get_text().strip()}")

        # rain
        rain = wind_status.find_next('span', 'temp')
        _rain = rain.get_text().strip()
        _data[ENTITY_RAIN] = float(_rain) if _rain else 0
        # print(f"rain: {rain.get_text().strip()}")

        rain_intensity = wind_status.find_next('span', 'valori2')
        regval = re.search("(?P<piog>[0-9.]*)\\D", rain_intensity.get_text().strip())
        _piogg = regval.group('piog')
        _data[ENTITY_RAIN_INTENSITY] = float(_piogg) if _piogg else 0
        # print(f"velpioggia: {regval.group('piog')}")

        rain_status = rain_intensity.find_next('span', 'avvisi')
        _data[ENTITY_RAIN_COMMENT] = rain_status.get_text().strip()
        # print(f"commentopiogg: {rain_status.get_text().strip()}")

        # station state
        station_state = rain_status.find_next('span', 'scrittine').find_next('span', 'scrittine') \
            .find_next('span', 'scrittine').find_next('span', 'scrittine')
        stato_text = station_state.get_text().split(':')
        _data[ENTITY_STATION_STATUS] = stato_text[1].strip()

        _station_available = True if _data[ENTITY_STATION_STATUS] == "ONLINE" else False

        for k, v in _data.items():
            await self.update_entity(station, k, v, _station_available)


class MeteoSystemWeatherSensor(Entity):
    """Representation of a MeteoSystem sensor from table's content."""

    def __init__(self, _station_name: str, _type: str):
        super().__init__()
        self.__station_name = _station_name
        self.__type = _type
        self.__internal_name = ' '.join([e.capitalize() for e in self.__type.split('_')])
        self._state = None
        self._unit_of_measurement = SENSOR_TYPES[self.__type][0]
        self._device_class = SENSOR_TYPES[self.__type][1]
        self._available = False
        self._icon = SENSOR_TYPES[self.__type][2]

        # changed property name since 2021.12
        if MAJOR_VERSION >= 2022 or (MAJOR_VERSION == 2021 and MINOR_VERSION == 12):
            MeteoSystemWeatherSensor.extra_state_attributes = property(lambda self: {ATTR_ATTRIBUTION: ATTRIBUTION})
        else:
            MeteoSystemWeatherSensor.device_state_attributes = property(lambda self: {ATTR_ATTRIBUTION: ATTRIBUTION})

    @property
    def name(self) -> str:
        """Return the name of the station."""
        return f"Meteo System {self.__station_name.capitalize()} {self.__internal_name}"

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return f"{DOMAIN}_{self.__station_name}_{self.__type}"

    @property
    def state(self) -> Optional[str]:
        return self._state

    @property
    def icon(self):
        """Entity icon."""
        return self._icon

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def type(self) -> str:
        return self.__type

    @property
    def station_name(self) -> str:
        return self.__station_name

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def device_class(self):
        """Return the device class of this entity, if any."""
        return self._device_class
