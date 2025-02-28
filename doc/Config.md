# CarConnectivity Plugin for Home Assistant MQTT Compatibility Config Options
The configuration for CarConnectivity is a .json file.
## General format
The general format is a `carConnectivity` section, followed by a list of connectors and plugins.
In the `carConnectivity` section you can set the global `log_level`.
Each connector or plugin needs a `type` attribute and a `config` section.
The `type` and config options specific to your connector or plugin can be found on their respective project page.
```json
{
    "carConnectivity": {
        "log_level": "error", // set the global log level, you can set individual log levels in the connectors and plugins
        "connectors": [
            {
                "type": "skoda", // Definition for a MySkoda account
                "config": {
                    "interval": 600, // Interval in which the server is checked in seconds
                    "username": "test@test.de", // Username of your MySkoda Account
                    "password": "testpassword123" // Password of your MySkoda Account
                }
            },
            {
                "type": "volkswagen", // Definition for a Volkswagen account
                "config": {
                    "interval": 300, // Interval in which the server is checked in seconds
                    "username": "test@test.de", // Username of your Volkswagen Account
                    "password": "testpassword123" // Username of your Volkswagen Account
                }
            }
        ],
        "plugins": [
            {
                "type": "mqtt_homeassistant", // Minimal definition for the Home Assistant Compatibility
                "config": {
                }
            }
        ]
    }
}
```
### Home Assistant MQTT Compatibility Plugin Options
These are the valid options for the Home Assistant MQTT compatibility plugin
```json
{
    "carConnectivity": {
        "connectors": [],
        "plugins": [
            {
                "type": "mqtt", // mqtt_homeassistant requires mqtt plugin to run!
                "config": {
                    "broker": "192.168.0.123", // Broker hostname or IP address
                    "username": "testuser", // Broker username to login
                    "password": "testuser", // Broker password to login
                }
            },
            {
                "type": "mqtt_homeassistant", // Definition for the Home Assistant MQTT Compatibility plugin
                "disabled": false, // You can disable plugins without removing them from the config completely
                "config": {
                    "log_level": "error", // The log level for the plugin. Otherwise uses the global log level
                    "homeassistant_prefix": "homeassistant" // Configured prefix of homeassistant
                }
            }
        ]
    }
}
```

### Connector Options
Valid Options for connectors can be found here:
* [CarConnectivity-connector-skoda Config Options](https://github.com/tillsteinbach/CarConnectivity-connector-skoda/tree/main/doc/Config.md)
* [CarConnectivity-connector-volkswagen Config Options](https://github.com/tillsteinbach/CarConnectivity-connector-volkswagen/tree/main/doc/Config.md)
* [CarConnectivity-connector-seatcupra Config Options](https://github.com/tillsteinbach/CarConnectivity-connector-seatcupra/tree/main/doc/Config.md)
* [CarConnectivity-connector-tronity Config Options](https://github.com/tillsteinbach/CarConnectivity-connector-tronity/tree/main/doc/Config.md)
