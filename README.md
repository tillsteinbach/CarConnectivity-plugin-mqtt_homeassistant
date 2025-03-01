

# CarConnectivity Plugin for MQTT compatibility with Home Assistant
[![GitHub sourcecode](https://img.shields.io/badge/Source-GitHub-green)](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant)](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/latest)
[![GitHub](https://img.shields.io/github/license/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant)](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/blob/master/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant)](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/issues)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/carconnectivity-plugin-mqtt_homeassistant?label=PyPI%20Downloads)](https://pypi.org/project/carconnectivity-plugin-mqtt_homeassistant/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/carconnectivity-plugin-mqtt_homeassistant)](https://pypi.org/project/carconnectivity-plugin-mqtt_homeassistant/)
[![Donate at PayPal](https://img.shields.io/badge/Donate-PayPal-2997d8)](https://www.paypal.com/donate?hosted_button_id=2BVFF5GJ9SXAJ)
[![Sponsor at Github](https://img.shields.io/badge/Sponsor-GitHub-28a745)](https://github.com/sponsors/tillsteinbach)

[CarConnectivity](https://github.com/tillsteinbach/CarConnectivity) is a python API to connect to various car services. If you want to provide data to Home Assistant the [CarConnectivity MQTT Plugin](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt) will enable the MQTT protocol. In order to improve the compatibility with Home Assistant, this plugin adds the Home Assistant Device Discovery for automatically provisioning devices in Home Assistant and adds further topics specifically for Home Assistant.

<img src="https://raw.githubusercontent.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/main/screenshots/homeassistant1.png" width="600">

### Install using PIP
If you want to use the CarConnectivity Plugin for Home Assistant, the easiest way is to obtain it from [PyPI](https://pypi.org/project/carconnectivity-plugin-mqtt_homeassistant/). Just install it using:
```bash
pip3 install carconnectivity-plugin-mqtt_homeassistant
```
after you installed [CarConnectivity](https://github.com/tillsteinbach/CarConnectivity) and the [CarConnectivity MQTT Plugin](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt).

### Install in your CarConnectivity Docker Container
Add `carconnectivity-plugin-mqtt_homeassistant` to the `ADDITIONAL_INSTALLS` environment variable (multiple entries can be separated by a space).
```
...
  carconnectivity-mqtt:
    image: "tillsteinbach/carconnectivity-mqtt:latest"
    environment:
      - ADDITIONAL_INSTALLS=carconnectivity-plugin-mqtt_homeassistant
...
```
## Configuration
In your carconnectivity.json configuration add a section for the mqtt_homeassistant plugin like this. A documentation of all possible config options can be found [here](https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/tree/main/doc/Config.md).
```
{
    "carConnectivity": {
        "connectors": [
            ...
        ]
        "plugins": [
            {
                "type": "mqtt", // Definition for the MQTT Connection
                "config": {
                    "broker": "192.168.0.123", // Broker hostname or IP address
                    "username": "testuser", // Broker username to login
                    "password": "testuser" // Broker password to login
                }
            },
            {
                "type": "mqtt_homeassistant",
                "config": {}
            }
        ]
    }
}
```
Afterwards you start CarConnectivity in your preferred way, e.g. using
```bash
carconnectivity-mqtt carconnectivity.json
```

Once the device is created in Home Assistant all Entities will display as "Not Available". The reason is that Home Assistant does not know the states yet. In order trigger a resend of all topics, restart CarConnectivity. This will make all entities available.

## Updates
If you want to update, the easiest way is:
```bash
pip3 install carconnectivity-plugin-mqtt_homeassistant --upgrade
```
