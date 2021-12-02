# MeteoSystem Weather Component for Home Assistant

## Installation
Copy into custom_components folder.

# Example configuration.yaml entry
```yml
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


# Thanks to
Aaron Godfrey and his [tutorial](https://aarongodfrey.dev/home%20automation/building_a_home_assistant_custom_component_part_1/)

