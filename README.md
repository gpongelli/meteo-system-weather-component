# MeteoSystem Weather Component for Home Assistant

## Installation
Copy into custom_components folder.

# Example configuration.yaml entry
```
sensor:
  - platform: meteo_system_weather
    url: https://...
    weather_stations:
      - station_name: "station 1"
      - station_name: "station 2"
      
  - platform: meteo_system_weather
    url: https://...
    weather_stations:
      - station_name: "station 3"
      - station_name: "station 4"
```

Then using the attrib through template platform
```
    sensors:
      meteo_status:
        friendly_name: "Humidity"
        value_template: >-
          {% if states.sensor.meteo_system_<station_name>.attributes['station_status'] -%}
            {{ state_attr('sensor.meteo_system_<station_name>', 'humidity') }}
          {%- else -%}OFFLINE{%- endif -%}
```

station_status attribute can be None or "ONLINE" string, that will execute the state_attr reading.


# Thanks to
Aaron Godfrey and his [tutorial](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)

