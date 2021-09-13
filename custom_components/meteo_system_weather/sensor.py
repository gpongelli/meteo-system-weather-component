"""MeteoSystem sensor platform."""
import logging
import re
from datetime import timedelta, datetime
from typing import Any, Callable, Dict, Tuple, Optional
from urllib import parse

import asyncio
import async_timeout

from bs4 import BeautifulSoup
import time
import aiohttp
from aiohttp import ClientError

import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    ATTR_NAME,
    CONF_URL,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
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
    ATTR_LAST_UPDATE,
    ATTR_TEMP,
    ATTR_HUMIDITY,
    ATTR_PERCEIVED_TEMP,
    ATTR_TEMP_STATUS,
    ATTR_PRESSURE,
    ATTR_WIND,
    ATTR_WIND_DIRECTION,
    ATTR_WIND_STATUS,
    ATTR_RAIN,
    ATTR_RAIN_STATUS,
    ATTR_RAIN_INTENSITY,
    ATTR_STATION_STATUS,
)

_LOGGER = logging.getLogger(__name__)

# Time between updating data from webpage
SCAN_INTERVAL = timedelta(minutes=3)


STATION_SCHEMA = vol.Schema(
    {vol.Required(CONF_STATION_NAME): cv.string}
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_WEATHER_STATIONS): vol.All(cv.ensure_list, [STATION_SCHEMA]),
        vol.Optional(CONF_URL): cv.url,
    }
)


URL_TIMESTAMP: Dict[str, Tuple] = {}


async def async_setup_platform(
    hass: HomeAssistantType,
    config: ConfigType,
    async_add_entities: Callable,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the sensor platform."""
    session = async_get_clientsession(hass)
    sensors = [MeteoSystemWeatherSensor(session, config[CONF_URL], weather) for weather in config[CONF_WEATHER_STATIONS]]
    async_add_entities(sensors, update_before_add=True)


class MeteoSystemWeatherSensor(Entity):
    """Representation of a MeteoSystem sensor from table's content."""
    def __init__(self, session: aiohttp.ClientSession, url: str, weather: Dict[str, str]):
        super().__init__()
        self._session = session
        self._url = url
        # self._names = list(map(lambda s: s.get(CONF_STATION_NAME, weather)))
        self._station_name = weather.get(CONF_STATION_NAME).lower()
        self._name = f"meteo_system_{self._station_name}"
        self.attrs: Dict[str, Any] = {CONF_STATION_NAME: self._station_name}
        self._state = None
        self._available = False
        self._html = None

    @property
    def name(self) -> str:
        """Return the name of the station."""
        return self._name

    @property
    def device_state_attributes(self) -> Dict[str, Any]:
        return self.attrs

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self._name

    @property
    def state(self) -> Optional[str]:
        return self._state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    async def async_update(self):
        await self.clean_attrs()

        try:
            _time_call = datetime.now()
            _saved, _ = URL_TIMESTAMP.get(self._url, (datetime(1970, 1, 1), ""))

            page_content = ""
            try:
                if (_time_call - _saved) >= SCAN_INTERVAL:
                    html = await asyncio.gather(self.fetch())

                    # with gather, the result is an aggregate list of returned values
                    page_content = html[0]

                    # update timestamp call for next comparison
                    URL_TIMESTAMP[self._url] = (_time_call, page_content)
                else:
                    # reuse saved html
                    _, html = URL_TIMESTAMP[self._url]
            except Exception as e:
                _LOGGER.exception(f"{e.__class__.__qualname__} while retrieving data from {self._url}")
            else:
                soup = await self.soup_page(page_content)
                # print(soup.title)
                station_name = soup.find_all('span', 'testotitolo')

                filtered = list(filter(self.filter_station, station_name))
                # print(filtered)

                # sometimes filtered array contains nothing
                if filtered:
                    await self.work_on_span(filtered[0])  # only one span element matching the input station name
        except ClientError:
            _LOGGER.exception(f"Error retrieving data from {self._url}")

    async def fetch(self):
        async with async_timeout.timeout(15):
            async with self._session.get(self._url) as response:
                return await response.text()

    async def clean_attrs(self):
        self.attrs[ATTR_LAST_UPDATE] = "--"
        self.attrs[ATTR_TEMP] = 0
        self.attrs[ATTR_HUMIDITY] = 0
        self.attrs[ATTR_PERCEIVED_TEMP] = 0
        self.attrs[ATTR_TEMP_STATUS] = "--"
        self.attrs[ATTR_PRESSURE] = 0
        self.attrs[ATTR_WIND] = 0
        self.attrs[ATTR_WIND_DIRECTION] = "--"
        self.attrs[ATTR_WIND_STATUS] = "--"
        self.attrs[ATTR_RAIN] = 0
        self.attrs[ATTR_RAIN_INTENSITY] = 0
        self.attrs[ATTR_RAIN_STATUS] = "--"
        self.attrs[ATTR_STATION_STATUS] = "UNREACHABLE"
        self._state = "UNREACHABLE"
        self._available = False

    async def soup_page(self, html):
        try:
            return BeautifulSoup(html, 'html.parser')
        except Exception as e:
            _LOGGER.exception(f"Error on BeautifulSoup: {str(e)}")

    def filter_station(self, span):
        if re.search(self._station_name, span.get_text(), re.IGNORECASE):
            return True
        else:
            return False

    async def work_on_span(self, tag):
        # print(tag.get_text().strip())
        span_elem = tag.find_next_sibling('span', 'valori3').next_sibling()
        # remove text in between

        # last update
        timest = list(map(lambda x: x.get_text(), [span_elem[0], span_elem[-1]]))
        # print(" ".join(timest).strip())
        self.attrs[ATTR_LAST_UPDATE] = " ".join(timest).strip()

        # temperature
        temp_span = span_elem[0].find_next('span', 'temp')
        self.attrs[ATTR_TEMP] = float(temp_span.get_text().strip())
        # print(f"TEMP: {temp_span.get_text().strip()}")

        # umidity
        umid_span = temp_span.find_next('span', 'temp')
        self.attrs[ATTR_HUMIDITY] = float(umid_span.get_text().strip())
        # print(f"UMID: {umid_span.get_text().strip()}")

        # perceived temp
        perc_span = umid_span.find_next('span', 'scrittine').find_next('span', 'valori2')
        regval = re.search("(?P<temp>[0-9.]*)\\D", perc_span.get_text().strip())
        self.attrs[ATTR_PERCEIVED_TEMP] = float(regval.group('temp'))
        # print(f"percepitavalore: {regval.group('temp')}")

        # temp comment
        temp_status = perc_span.find_next('span', 'avvisi')
        self.attrs[ATTR_TEMP_STATUS] = temp_status.get_text().strip()
        # print(f"commentotemp: {temp_status.get_text().strip()}")

        # pressure
        pressure = temp_status.find_next('td', 'bordoalto').find_next('span', 'scrittine')
        pressure_text = pressure.get_text().split(':')
        regval = re.search("(?P<press>[0-9.]*)\\D", pressure_text[1].strip())
        self.attrs[ATTR_PRESSURE] = float(regval.group('press'))
        # print(f"pressione: {regval.group('press')}")

        # wind
        wind_speed = pressure.find_next('span', 'temp')
        self.attrs[ATTR_WIND] = float(wind_speed.get_text().strip())
        # print(f"velvento: {velvento.get_text().strip()}")

        wind_direction = wind_speed.find_next('span', 'valor2')
        _direct = wind_direction.get_text().strip().split()[1]
        self.attrs[ATTR_WIND_DIRECTION] = _direct
        # print(f"dirvento: {dirvento.get_text().strip()}")

        wind_status = wind_direction.find_next('span', 'avvisi').find_next('span', 'avvisi')
        # commentovento = mediavento.find_next('span', 'avvisi')
        self.attrs[ATTR_WIND_STATUS] = wind_status.get_text().strip()
        # print(f"commentovento: {commentovento.get_text().strip()}")

        # rain
        rain = wind_status.find_next('span', 'temp')
        self.attrs[ATTR_RAIN] = float(rain.get_text().strip())
        # print(f"rain: {rain.get_text().strip()}")
        rain_intensity = wind_status.find_next('span', 'valori2')
        regval = re.search("(?P<piog>[0-9.]*)\\D", rain_intensity.get_text().strip())
        self.attrs[ATTR_RAIN_INTENSITY] = float(regval.group('piog'))
        # print(f"velpioggia: {regval.group('piog')}")
        rain_status = rain_intensity.find_next('span', 'avvisi')
        self.attrs[ATTR_RAIN_STATUS] = rain_status.get_text().strip()
        # print(f"commentopiogg: {rain_status.get_text().strip()}")

        # station state
        station_state = rain_status.find_next('span', 'scrittine').find_next('span', 'scrittine') \
            .find_next('span', 'scrittine').find_next('span', 'scrittine')
        stato_text = station_state.get_text().split(':')
        self.attrs[ATTR_STATION_STATUS] = stato_text[1].strip()
        self._state = self.attrs[ATTR_STATION_STATUS]
        # print(f"stato : {stato_text[1].strip()}")

        self._available = True if self._state == "ONLINE" else False
