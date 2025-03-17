"""Module implements the plugin to improve compatibility with Home Assistant."""
from __future__ import annotations
from typing import TYPE_CHECKING

from enum import Enum
import logging
import json

from carconnectivity.util import config_remove_credentials
from carconnectivity.vehicle import GenericVehicle, ElectricVehicle
from carconnectivity.drive import ElectricDrive, CombustionDrive, DieselDrive
from carconnectivity.observable import Observable
from carconnectivity.errors import ConfigurationError
from carconnectivity.attributes import FloatAttribute, EnumAttribute, GenericAttribute
from carconnectivity.position import Position
from carconnectivity.charging import Charging
from carconnectivity.doors import Doors
from carconnectivity.climatization import Climatization
from carconnectivity.units import Temperature
from carconnectivity._version import __version__ as __carconnectivity_version__

from carconnectivity_plugins.base.plugin import BasePlugin

from carconnectivity_plugins.mqtt.plugin import Plugin as MqttPlugin, ImageFormat

from carconnectivity_plugins.mqtt_homeassistant._version import __version__

SUPPORT_IMAGES = False
try:
    from PIL import Image  # pylint: disable=unused-import # noqa: F401
    SUPPORT_IMAGES = True
except ImportError:
    pass

if TYPE_CHECKING:
    from typing import Dict, Optional, Any
    from carconnectivity.carconnectivity import CarConnectivity

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.mqtt_homeassistant")


class Plugin(BasePlugin):  # pylint: disable=too-many-instance-attributes
    """
    Plugin class for Home Assistant Compatibility.
    Args:
        car_connectivity (CarConnectivity): An instance of CarConnectivity.
        config (Dict): Configuration dictionary containing connection details.
    """
    def __init__(self, plugin_id: str, car_connectivity: CarConnectivity, config: Dict) -> None:
        BasePlugin.__init__(self, plugin_id=plugin_id, car_connectivity=car_connectivity, config=config, log=LOG)

        self.mqtt_plugin: Optional[MqttPlugin] = None
        self.homeassistant_discovery: bool = True
        self.homeassistant_discovery_hashes: Dict[str, int] = {}

        LOG.info("Loading mqtt_homeassistant plugin with config %s", config_remove_credentials(config))

        if 'homeassistant_prefix' in config:
            self.active_config['homeassistant_prefix'] = config['homeassistant_prefix']
        else:
            self.active_config['homeassistant_prefix'] = 'homeassistant'

    def startup(self) -> None:
        LOG.info("Starting MQTT Home Assistant plugin")
        # Try to find the MQTT plugin in car connectivity
        if 'mqtt' not in self.car_connectivity.plugins.plugins:
            raise ConfigurationError("MQTT plugin not found, MQTT Home Assistant plugin will not work")
        if not isinstance(self.car_connectivity.plugins.plugins['mqtt'], MqttPlugin):
            raise ConfigurationError("MQTT plugin is not an instance of MqttPlugin, MQTT Home Assistant plugin will not work")
        self.mqtt_plugin = self.car_connectivity.plugins.plugins['mqtt']

        if self.mqtt_plugin is None:
            raise ConfigurationError("MQTT plugin is None, MQTT Home Assistant plugin will not work")

        self.mqtt_plugin.mqtt_client.add_on_message_callback(self._on_message_callback)
        self.mqtt_plugin.mqtt_client.add_on_connect_callback(self._on_connect_callback)

        flags: Observable.ObserverEvent = Observable.ObserverEvent.ENABLED | Observable.ObserverEvent.DISABLED | Observable.ObserverEvent.VALUE_CHANGED
        self.car_connectivity.add_observer(self._on_carconnectivity_event, flags, priority=Observable.ObserverPriority.USER_MID, on_transaction_end=True)

        self.healthy._set_value(value=True)  # pylint: disable=protected-access
        LOG.debug("Starting  MQTT Home Assistant plugin done")

    def shutdown(self) -> None:
        if self.mqtt_plugin is not None:
            self.mqtt_plugin.mqtt_client.remove_on_message_callback(self._on_message_callback)
            self.mqtt_plugin.mqtt_client.remove_on_connect_callback(self._on_connect_callback)
        return super().shutdown()

    def get_version(self) -> str:
        return __version__

    def get_type(self) -> str:
        return "carconnectivity-plugin-mqtt_homeassistant"

    def get_name(self) -> str:
        return "MQTT Home Assistant Plugin"

    def _publish_homeassistant_discovery(self, force=False) -> None:  # pylint: disable=too-many-branches
        for vehicle in self.car_connectivity.garage.list_vehicles():
            if vehicle.enabled:
                self._publish_homeassistant_discovery_vehicle(vehicle, force=force)
        if self.mqtt_plugin is None:
            raise ValueError('MQTT plugin is None')
        car_connectivity_id: str = self.mqtt_plugin.mqtt_client.prefix.replace('/', '-')
        discovery_topic = f'{self.active_config["homeassistant_prefix"]}/device/carconnectivity-{car_connectivity_id}/config'
        discovery_message = {
            'device': {
                'ids': car_connectivity_id,
                'name': 'CarConnectivity',
                'mf': 'Till Steinbach and the CarConnectivity Community',
                'sw': __carconnectivity_version__,
            },
            'origin': {
                'name': 'CarConnectivity',
                'sw': __version__,
                'url': 'https://github.com/tillsteinbach/CarConnectivity'
            },
            'cmps': {}
        }
        for connector in self.car_connectivity.connectors.connectors.values():
            if connector.enabled:
                if connector.healthy.enabled and connector.healthy.value is not None:
                    discovery_message['cmps'][f'{car_connectivity_id}_{connector.id}_healthy'] = {
                        'p': 'binary_sensor',
                        'device_class': 'running',
                        'name': f'{connector.get_name()} Healthy',
                        'icon': 'mdi:check',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{connector.healthy.get_absolute_path()}',
                        'payload_off': 'False',
                        'payload_on': 'True',
                        'unique_id': f'{car_connectivity_id}_{connector.id}_healthy'
                    }
                for child in connector.children:
                    if child.id == 'connection_state' and isinstance(child, EnumAttribute) and child.enabled:
                        discovery_message['cmps'][f'{car_connectivity_id}_{connector.id}_connection_state'] = {
                            'p': 'sensor',
                            'device_class': 'enum',
                            'name': f'{connector.get_name()} Connection State',
                            'icon': 'mdi:lan-connect',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{child.get_absolute_path()}',
                            'payload_off': 'False',
                            'payload_on': 'True',
                            'unique_id': f'{car_connectivity_id}_{connector.id}_connection_state'
                        }
                        if child.value_type is not None and issubclass(child.value_type, Enum):
                            discovery_message['cmps'][f'{car_connectivity_id}_{connector.id}_connection_state']['options'] = \
                                [item.value for item in child.value_type]

        for plugin in self.car_connectivity.plugins.plugins.values():
            if plugin.enabled:
                if plugin.healthy.enabled and plugin.healthy.value is not None:
                    discovery_message['cmps'][f'{car_connectivity_id}_{plugin.id}_healthy'] = {
                        'p': 'binary_sensor',
                        'device_class': 'running',
                        'name': f'{plugin.get_name()} Healthy',
                        'icon': 'mdi:check',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{plugin.healthy.get_absolute_path()}',
                        'payload_off': 'False',
                        'payload_on': 'True',
                        'unique_id': f'{car_connectivity_id}_{plugin.id}_healthy'
                    }
                for child in plugin.children:
                    if child.id == 'connection_state' and isinstance(child, EnumAttribute) and child.enabled:
                        discovery_message['cmps'][f'{car_connectivity_id}_{plugin.id}_connection_state'] = {
                            'p': 'sensor',
                            'device_class': 'enum',
                            'name': f'{plugin.get_name()} Connected',
                            'icon': 'mdi:lan-connect',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{child.get_absolute_path()}',
                            'payload_off': 'False',
                            'payload_on': 'True',
                            'unique_id': f'{car_connectivity_id}_{plugin.id}_connection_state'
                        }
                        if child.value_type is not None and issubclass(child.value_type, Enum):
                            discovery_message['cmps'][f'{car_connectivity_id}_{plugin.id}_connection_state']['options'] = \
                                [item.value for item in child.value_type]
        for sensor in discovery_message['cmps'].values():
            sensor['availability'] = [{
                'topic': f'{self.mqtt_plugin.mqtt_client.prefix}{self.mqtt_plugin.connection_state.get_absolute_path()}',
                'payload_not_available': 'disconnected',
                'payload_available': 'connected',
                }]
        discovery_hash = hash(json.dumps(discovery_message))
        if car_connectivity_id not in self.homeassistant_discovery_hashes \
                or self.homeassistant_discovery_hashes[car_connectivity_id] != discovery_hash or force:
            self.homeassistant_discovery_hashes[car_connectivity_id] = discovery_hash
            LOG.debug("Publishing Home Assistant discovery message for CarConnectivity with Connectors and Plugins")
            self.mqtt_plugin.mqtt_client.publish(topic=discovery_topic, qos=1, retain=False, payload=json.dumps(discovery_message, indent=4))

    # pylint: disable-next=too-many-branches, too-many-statements, too-many-locals
    def _publish_homeassistant_discovery_vehicle(self, vehicle: GenericVehicle, force=False) -> None:
        """
        Publish the Home Assistant discovery message.

        Args:
            None
        """
        if self.mqtt_plugin is None:
            raise ValueError('MQTT plugin is None')
        if vehicle.vin is None or vehicle.vin.value is None:
            raise ValueError('Vehicle VIN is None')
        # When the MQTT client is not connected, we can't publish the discovery message
        if not self.mqtt_plugin.mqtt_client.is_connected():
            return
        vin: str = vehicle.vin.value
        discovery_topic = f'{self.active_config["homeassistant_prefix"]}/device/{vin}/config'
        discovery_message = {
            'device': {
                'ids': vin,
                'sn': vin,
            },
            'origin': {
                'name': 'carconnectivity-plugin-mqtt',
                'sw': __version__,
                'url': 'https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt'
            },
            'cmps': {}
        }
        if vehicle.name.enabled and vehicle.name.value is not None:
            discovery_message['device']['name'] = vehicle.name.value
        if vehicle.manufacturer.enabled and vehicle.manufacturer.value is not None:
            discovery_message['device']['mf'] = vehicle.manufacturer.value
        if vehicle.model.enabled and vehicle.model.value is not None:
            discovery_message['device']['mdl'] = vehicle.model.value
        if vehicle.model_year.enabled and vehicle.model_year.value is not None:
            discovery_message['device']['hw'] = str(vehicle.model_year.value)
        if vehicle.software is not None and vehicle.software.enabled and vehicle.software.version.enabled and vehicle.software.version.value is not None:
            discovery_message['device']['sw'] = vehicle.software.version.value

        if vehicle.commands.enabled and 'wake-sleep' in vehicle.commands.commands:
            discovery_message['cmps'][f'{vin}_wake'] = {
                'p': 'button',
                'name': 'Wakeup',
                'icon': 'mdi:sleep-off',
                'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.commands.commands["wake-sleep"].get_absolute_path()}'
                + '_writetopic',
                'payload_press': 'wake',
                'unique_id': f'{vin}_wake'
            }
        if vehicle.odometer.enabled and vehicle.odometer.value is not None and vehicle.odometer.unit is not None:
            discovery_message['cmps'][f'{vin}_odometer'] = {
                'p': 'sensor',
                'device_class': 'distance',
                'icon': 'mdi:counter',
                'name': 'Odometer',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.odometer.get_absolute_path()}',
                'unit_of_measurement': vehicle.odometer.unit.value,
                'unique_id': f'{vin}_odometer',
            }
        if vehicle.state.enabled and vehicle.state.value is not None:
            discovery_message['cmps'][f'{vin}_state'] = {
                'p': 'sensor',
                'device_class': 'enum',
                'icon': 'mdi:car-hatchback',
                'name': 'Vehicle State',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.state.get_absolute_path()}',
                'unique_id': f'{vin}_state'
            }
            if vehicle.state.value_type is not None and issubclass(vehicle.state.value_type, Enum):
                discovery_message['cmps'][f'{vin}_state']['options'] = [item.value for item in vehicle.state.value_type]
        if vehicle.connection_state.enabled and vehicle.connection_state.value is not None:
            discovery_message['cmps'][f'{vin}_connection_state'] = {
                'p': 'sensor',
                'device_class': 'enum',
                'icon': 'mdi:car-connected',
                'name': 'Connection State',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.connection_state.get_absolute_path()}',
                'unique_id': f'{vin}_connection_state'
            }
            if vehicle.connection_state.value_type is not None and issubclass(vehicle.connection_state.value_type, Enum):
                discovery_message['cmps'][f'{vin}_connection_state']['options'] = [item.value for item in vehicle.connection_state.value_type]
        if vehicle.drives is not None and vehicle.drives.enabled:  # pylint: disable=too-many-nested-blocks
            if vehicle.drives.total_range.enabled and vehicle.drives.total_range.value is not None and vehicle.drives.total_range.unit is not None:
                discovery_message['cmps'][f'{vin}_total_range'] = {
                    'p': 'sensor',
                    'device_class': 'distance',
                    'name': 'Total Range',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.drives.total_range.get_absolute_path()}',
                    'unit_of_measurement': vehicle.drives.total_range.unit.value,
                    'unique_id': f'{vin}_total_range'
                }
            for drive_id, drive in vehicle.drives.drives.items():
                if drive.enabled:
                    if drive.range.enabled and drive.range.value is not None and drive.range.unit is not None:
                        discovery_message['cmps'][f'{vin}_{drive_id}_range'] = {
                            'p': 'sensor',
                            'device_class': 'distance',
                            'name': f'Range ({drive_id})',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.range.get_absolute_path()}',
                            'unit_of_measurement': drive.range.unit.value,
                            'unique_id': f'{vin}_{drive_id}_range'
                        }
                    if isinstance(drive, CombustionDrive):
                        if drive.level.enabled and drive.level.value is not None and drive.level.unit is not None:
                            discovery_message['cmps'][f'{vin}_{drive_id}_level'] = {
                                'p': 'sensor',
                                'name': f'Tank ({drive_id})',
                                'icon': 'mdi:gas-station',
                                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.level.get_absolute_path()}',
                                'unit_of_measurement': drive.level.unit.value,
                                'unique_id': f'{vin}_{drive_id}_level'
                            }
                        if isinstance(drive, DieselDrive):
                            if drive.adblue_level.enabled and drive.adblue_level.value is not None and drive.adblue_level.unit is not None:
                                discovery_message['cmps'][f'{vin}_{drive_id}_adbluelevel'] = {
                                    'p': 'sensor',
                                    'name': f'AdBlue Tank ({drive_id})',
                                    'icon': 'mdi:gas-station',
                                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.adblue_level.get_absolute_path()}',
                                    'unit_of_measurement': drive.adblue_level.unit.value,
                                    'unique_id': f'{vin}_{drive_id}_adbluelevel'
                                }
                            if drive.adblue_range.enabled and drive.adblue_range.value is not None and drive.adblue_range.unit is not None:
                                discovery_message['cmps'][f'{vin}_{drive_id}_adbluerange'] = {
                                    'p': 'sensor',
                                    'device_class': 'distance',
                                    'name': f'AdBlue Range ({drive_id})',
                                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.adblue_range.get_absolute_path()}',
                                    'unit_of_measurement': drive.adblue_range.unit.value,
                                    'unique_id': f'{vin}_{drive_id}_adbluerange'
                                }
                    elif isinstance(drive, ElectricDrive):
                        if drive.level.enabled and drive.level.value is not None and drive.level.unit is not None:
                            discovery_message['cmps'][f'{vin}_{drive_id}_level'] = {
                                'p': 'sensor',
                                'device_class': 'battery',
                                'icon': 'mdi:battery',
                                'name': f'SoC ({drive_id})',
                                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.level.get_absolute_path()}',
                                'unit_of_measurement': drive.level.unit.value,
                                'unique_id': f'{vin}_{drive_id}_level'
                            }
                        if drive.battery is not None and drive.battery.enabled:
                            if drive.battery.temperature.enabled and drive.battery.temperature.value is not None and drive.battery.temperature.unit is not None:
                                discovery_message['cmps'][f'{vin}_{drive_id}_battery_temperature'] = {
                                    'p': 'sensor',
                                    'device_class': 'temperature',
                                    'icon': 'mdi:thermometer-lines',
                                    'name': f'Battery Temperature ({drive_id})',
                                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.battery.temperature.get_absolute_path()}',
                                    'unit_of_measurement': drive.battery.temperature.unit.value,
                                    'unique_id': f'{vin}_{drive_id}_battery_temperature'
                                }
        if vehicle.doors is not None and vehicle.doors.enabled:
            if vehicle.doors.open_state.enabled and vehicle.doors.open_state.value is not None:
                discovery_message['cmps'][f'{vin}_open_state'] = {
                    'p': 'binary_sensor',
                    'device_class': 'door',
                    'name': 'Door Open State',
                    'icon': 'mdi:car-door',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.open_state.get_absolute_path()}',
                    'payload_off': 'closed',
                    'payload_on': 'open',
                    'unique_id': f'{vin}_open_state'
                }
            if vehicle.doors.lock_state.enabled and vehicle.doors.lock_state.value is not None:
                if 'lock-unlock' in vehicle.doors.commands.commands:
                    discovery_message['cmps'][f'{vin}_lock_unlock'] = {
                        'p': 'lock',
                        'name': 'Lock/Unlock',
                        'icon': 'mdi:car-door-lock',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.lock_state.get_absolute_path()}',
                        'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.commands.commands["lock-unlock"].get_absolute_path()}'
                        + '_writetopic',
                        'payload_lock': 'lock',
                        'payload_unlock': 'unlock',
                        'state_locked': 'locked',
                        'state_unlocked': 'unlocked',
                        'unique_id': f'{vin}_lock_unlock'
                    }
                else:
                    discovery_message['cmps'][f'{vin}_lock_state'] = {
                        'p': 'binary_sensor',
                        'device_class': 'lock',
                        'name': 'Lock State',
                        'icon': 'mdi:car-door-lock',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.lock_state.get_absolute_path()}',
                        'payload_on': 'unlocked',
                        'payload_off': 'locked',
                        'unique_id': f'{vin}_lock_state'
                    }
            for door_id, door in vehicle.doors.doors.items():
                if door.enabled:
                    if door.open_state.enabled and door.open_state.value is not None \
                            and door.open_state.value not in [Doors.OpenState.UNKNOWN, Doors.OpenState.INVALID, Doors.OpenState.UNSUPPORTED]:
                        discovery_message['cmps'][f'{vin}_{door_id}_door_open_state'] = {
                            'p': 'binary_sensor',
                            'device_class': 'door',
                            'name': f'Door Open State ({door_id})',
                            'icon': 'mdi:car-door',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{door.open_state.get_absolute_path()}',
                            'payload_off': 'closed',
                            'payload_on': 'open',
                            'unique_id': f'{vin}_{door_id}_door_open_state'
                        }
                    if door.lock_state.enabled and door.lock_state.value is not None \
                            and door.lock_state.value not in [Doors.LockState.UNKNOWN, Doors.LockState.INVALID]:
                        discovery_message['cmps'][f'{vin}_{door_id}_door_lock_state'] = {
                            'p': 'binary_sensor',
                            'device_class': 'lock',
                            'name': f'Lock State ({door_id})',
                            'icon': 'mdi:car-door-lock',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{door.lock_state.get_absolute_path()}',
                            'payload_on': 'unlocked',
                            'payload_off': 'locked',
                            'unique_id': f'{vin}_{door_id}_door_lock_state'
                        }
        if vehicle.windows is not None and vehicle.windows.enabled:
            if vehicle.windows.open_state.enabled and vehicle.windows.open_state.value is not None:
                discovery_message['cmps'][f'{vin}_window_open_state'] = {
                    'p': 'binary_sensor',
                    'device_class': 'window',
                    'name': 'Window Open State',
                    'icon': 'mdi:window-open',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.windows.open_state.get_absolute_path()}',
                    'payload_off': 'closed',
                    'payload_on': 'open',
                    'unique_id': f'{vin}_window_open_state'
                }
            for window_id, window in vehicle.windows.windows.items():
                if window.enabled:
                    if window.open_state.enabled and window.open_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{window_id}_window_open_state'] = {
                            'p': 'binary_sensor',
                            'device_class': 'window',
                            'name': f'Window Open State ({window_id})',
                            'icon': 'mdi:window-open',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{window.open_state.get_absolute_path()}',
                            'payload_off': 'closed',
                            'payload_on': 'open',
                            'unique_id': f'{vin}_{window_id}_window_open_state'
                        }
        if vehicle.lights is not None and vehicle.lights.enabled:
            if vehicle.lights.light_state.enabled and vehicle.lights.light_state.value is not None:
                discovery_message['cmps'][f'{vin}_light_state'] = {
                    'p': 'binary_sensor',
                    'name': 'Light State',
                    'icon': 'mdi:car-light-dimmed',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.lights.light_state.get_absolute_path()}',
                    'payload_off': 'off',
                    'payload_on': 'on',
                    'unique_id': f'{vin}_light_state'
                }
            for light_id, light in vehicle.lights.lights.items():
                if light.enabled:
                    if light.light_state.enabled and light.light_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{light_id}_state'] = {
                            'p': 'binary_sensor',
                            'name': f'Light State ({light_id})',
                            'icon': 'mdi:car-light-dimmed',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{light.light_state.get_absolute_path()}',
                            'payload_off': 'off',
                            'payload_on': 'on',
                            'unique_id': f'{vin}_{light_id}_state'
                        }
        if vehicle.window_heatings is not None and vehicle.window_heatings.enabled:
            if vehicle.window_heatings.commands.enabled and 'start-stop' in vehicle.window_heatings.commands.commands \
                    and vehicle.window_heatings.heating_state.enabled and vehicle.window_heatings.heating_state.value is not None:
                discovery_message['cmps'][f'{vin}_window_heating_start_stop'] = {
                    'p': 'switch',
                    'name': 'Start/Stop Window Heating',
                    'icon': 'mdi:car-defrost-front',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.window_heatings.heating_state.get_absolute_path()}',
                    'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.window_heatings.commands.commands["start-stop"].get_absolute_path()}'
                    + '_writetopic',
                    'payload_on': 'start',
                    'payload_off': 'stop',
                    'state_on': 'on',
                    'state_off': 'off',
                    'unique_id': f'{vin}_window_heating_start_stop'
                }
            if vehicle.window_heatings.heating_state.enabled and vehicle.window_heatings.heating_state.value is not None:
                discovery_message['cmps'][f'{vin}_window_heating_state'] = {
                    'p': 'binary_sensor',
                    'name': 'Window Heating State',
                    'icon': 'mdi:car-defrost-front',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.window_heatings.heating_state.get_absolute_path()}',
                    'payload_off': 'off',
                    'payload_on': 'on',
                    'unique_id': f'{vin}_window_heating_state'
                }
            for window_id, window in vehicle.window_heatings.windows.items():
                if window.enabled:
                    if window.heating_state.enabled and window.heating_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{window_id}_window_heating_state'] = {
                            'p': 'binary_sensor',
                            'name': f'Window Heating State ({window_id})',
                            'icon': 'mdi:car-defrost-front',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{window.heating_state.get_absolute_path()}',
                            'payload_off': 'off',
                            'payload_on': 'on',
                            'unique_id': f'{vin}_{window_id}_window_heating_state'
                        }
                    if 'rear' in window_id:
                        discovery_message['cmps'][f'{vin}_{window_id}_window_heating_state']['icon'] = 'mdi:car-defrost-rear'

        if vehicle.position.enabled:
            # pylint: disable-next=too-many-boolean-expressions
            if vehicle.position.latitude.enabled and vehicle.position.latitude.value is not None \
                    and vehicle.position.longitude.enabled and vehicle.position.longitude.value is not None \
                    and vehicle.position.latitude.unit is not None and vehicle.position.longitude.unit is not None:
                discovery_message['cmps'][f'{vin}_latitude'] = {
                    'p': 'sensor',
                    'name': 'Position Latitude',
                    'icon': 'mdi:latitude',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.latitude.get_absolute_path()}',
                    'unit_of_measurement': vehicle.position.latitude.unit.value,
                    'unique_id': f'{vin}_latitude'
                }
                discovery_message['cmps'][f'{vin}_longitude'] = {
                    'p': 'sensor',
                    'name': 'Position Longitude',
                    'icon': 'mdi:longitude',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.longitude.get_absolute_path()}',
                    'unit_of_measurement': vehicle.position.longitude.unit.value,
                    'unique_id': f'{vin}_longitude'
                }
            if vehicle.position.position_type.enabled and vehicle.position.position_type.value is not None:
                discovery_message['cmps'][f'{vin}_position_type'] = {
                    'p': 'sensor',
                    'device_class': 'enum',
                    'icon': 'mdi:map-marker',
                    'name': 'Position Type',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.position_type.get_absolute_path()}',
                    'unique_id': f'{vin}_position_type'
                }
                if vehicle.position.position_type.value_type is not None and issubclass(vehicle.position.position_type.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_position_type']['options'] = [item.value for item in vehicle.position.position_type.value_type]
        if vehicle.climatization.enabled:
            if vehicle.climatization.state.enabled and vehicle.climatization.state.value is not None:
                discovery_message['cmps'][f'{vin}_climatization_state'] = {
                    'p': 'sensor',
                    'icon': 'mdi:air-conditioner',
                    'device_class': 'enum',
                    'name': 'Climatization State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.state.get_absolute_path()}',
                    'unique_id': f'{vin}_climatization_state'
                }
                if vehicle.climatization.state.value_type is not None and issubclass(vehicle.climatization.state.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_climatization_state']['options'] = [item.value for item in vehicle.climatization.state.value_type]
            if vehicle.climatization.commands.enabled and 'start-stop' in vehicle.climatization.commands.commands:
                def __mode_to_command_hook(attribute: GenericAttribute, value: Any) -> Any:
                    del attribute
                    if value == 'off':
                        return 'stop'
                    if value == 'auto':
                        return 'start'
                    return value
                # pylint: disable-next=protected-access
                vehicle.climatization.commands.commands['start-stop']._add_on_set_hook(__mode_to_command_hook, early_hook=True)
                discovery_message['cmps'][f'{vin}_climatization_start_stop'] = {
                        'p': 'climate',
                        'name': 'Start/Stop Climatization',
                        'icon': 'mdi:air-conditioner',
                        'action_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.get_absolute_path()}/hvac_action',
                        'mode_command_topic':
                        f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.commands.commands["start-stop"].get_absolute_path()}_writetopic',
                        'mode_state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.get_absolute_path()}/hvac_mode',
                        'modes': ['off', 'auto'],
                        'power_command_topic':
                        f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.commands.commands["start-stop"].get_absolute_path()}'
                        + '_writetopic',
                        'payload_on': 'start',
                        'payload_off': 'stop',
                        'unique_id': f'{vin}_climatization_start_stop'
                    }
            if vehicle.climatization.settings.enabled and vehicle.climatization.settings.target_temperature.enabled:
                if vehicle.climatization.settings.target_temperature.value is not None:
                    discovery_message['cmps'][f'{vin}_climatization_start_stop']['temperature_state_topic'] = \
                        f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.settings.target_temperature.get_absolute_path()}'
                if vehicle.climatization.settings.target_temperature.maximum is not None:
                    discovery_message['cmps'][f'{vin}_climatization_start_stop']['max_temp'] = vehicle.climatization.settings.target_temperature.maximum
                if vehicle.climatization.settings.target_temperature.minimum is not None:
                    discovery_message['cmps'][f'{vin}_climatization_start_stop']['min_temp'] = vehicle.climatization.settings.target_temperature.minimum
                if vehicle.climatization.settings.target_temperature.precision is not None:
                    discovery_message['cmps'][f'{vin}_climatization_start_stop']['temp_step'] = vehicle.climatization.settings.target_temperature.precision
                if vehicle.climatization.settings.target_temperature.is_changeable:
                    discovery_message['cmps'][f'{vin}_climatization_start_stop']['temperature_command_topic'] = \
                        f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.settings.target_temperature.get_absolute_path()}_writetopic'
                if vehicle.climatization.settings.target_temperature.unit is not None:
                    if vehicle.climatization.settings.target_temperature.unit.value == Temperature.C:
                        discovery_message['cmps'][f'{vin}_climatization_start_stop']['temperature_unit'] = 'C'
                    elif vehicle.climatization.settings.target_temperature.unit.value == Temperature.F:
                        discovery_message['cmps'][f'{vin}_climatization_start_stop']['temperature_unit'] = 'F'
            if vehicle.climatization.estimated_date_reached.enabled and vehicle.climatization.estimated_date_reached.value is not None:
                discovery_message['cmps'][f'{vin}_climatization_estimated_date_reached'] = {
                    'p': 'sensor',
                    'device_class': 'timestamp',
                    'icon': 'mdi:clock-end',
                    'name': 'Climatization Estimated Date Reached',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.estimated_date_reached.get_absolute_path()}',
                    'unique_id': f'{vin}_climatization_estimated_date_reached'
                }
        if vehicle.outside_temperature.enabled and vehicle.outside_temperature.value is not None and vehicle.outside_temperature.unit is not None:
            discovery_message['cmps'][f'{vin}_outside_temperature'] = {
                'p': 'sensor',
                'device_class': 'temperature',
                'icon': 'mdi:sun-thermometer-outline',
                'name': 'Outside Temperature',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.outside_temperature.get_absolute_path()}',
                'unit_of_measurement': vehicle.outside_temperature.unit.value,
                'unique_id': f'{vin}_outside_temperature'
            }
        if vehicle.maintenance.enabled:
            if vehicle.maintenance.inspection_due_at.enabled and vehicle.maintenance.inspection_due_at.value is not None:
                discovery_message['cmps'][f'{vin}_inspection_due_at'] = {
                    'p': 'sensor',
                    'device_class': 'timestamp',
                    'icon': 'mdi:tools',
                    'name': 'Inspection Due At',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.inspection_due_at.get_absolute_path()}',
                    'unique_id': f'{vin}_inspection_due_at'
                }
            if vehicle.maintenance.inspection_due_after.enabled and vehicle.maintenance.inspection_due_after.value is not None \
                    and vehicle.maintenance.inspection_due_after.unit is not None:
                discovery_message['cmps'][f'{vin}_inspection_due_after'] = {
                    'p': 'sensor',
                    'device_class': 'distance',
                    'icon': 'mdi:tools',
                    'name': 'Inspection Due After',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.inspection_due_after.get_absolute_path()}',
                    'unit_of_measurement': vehicle.maintenance.inspection_due_after.unit.value,
                    'unique_id': f'{vin}_inspection_due_after'
                }
            if vehicle.maintenance.oil_service_due_at.enabled and vehicle.maintenance.oil_service_due_at.value is not None:
                discovery_message['cmps'][f'{vin}_oil_service_due_at'] = {
                    'p': 'sensor',
                    'device_class': 'timestamp',
                    'icon': 'mdi:oil',
                    'name': 'Oil Service Due At',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.oil_service_due_at.get_absolute_path()}',
                    'unique_id': f'{vin}_oil_service_due_at'
                }
            if vehicle.maintenance.oil_service_due_after.enabled and vehicle.maintenance.oil_service_due_after.value is not None \
                    and vehicle.maintenance.oil_service_due_after.unit is not None:
                discovery_message['cmps'][f'{vin}_oil_service_due_after'] = {
                    'p': 'sensor',
                    'device_class': 'distance',
                    'icon': 'mdi:oil',
                    'name': 'Oil Service Due After',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.oil_service_due_after.get_absolute_path()}',
                    'unit_of_measurement': vehicle.maintenance.oil_service_due_after.unit.value,
                    'unique_id': f'{vin}_oil_service_due_after'
                }
        if SUPPORT_IMAGES and self.mqtt_plugin.mqtt_client.image_format == ImageFormat.PNG:
            if vehicle.images.enabled:
                for image_id, image in vehicle.images.images.items():
                    if image.enabled and image.value is not None:
                        discovery_message['cmps'][f'{vin}_{image_id}_image'] = {
                            'p': 'image',
                            'name': f'Image ({image_id})',
                            'image_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{image.get_absolute_path()}',
                            'content_type': 'image/png',
                            'unique_id': f'{vin}_{image_id}_image'
                        }
        if isinstance(vehicle, ElectricVehicle):
            if vehicle.charging.connector.connection_state.enabled and vehicle.charging.connector.connection_state.value is not None:
                if vehicle.charging.commands.enabled and 'start-stop' in vehicle.charging.commands.commands \
                        and vehicle.charging.state.enabled and vehicle.charging.state.value is not None:
                    discovery_message['cmps'][f'{vin}_charging_start_stop'] = {
                        'p': 'switch',
                        'name': 'Start/Stop Charging',
                        'icon': 'mdi:ev-station',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.get_absolute_path()}/binarystate',
                        'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.commands.commands["start-stop"].get_absolute_path()}'
                        + '_writetopic',
                        'payload_on': 'start',
                        'payload_off': 'stop',
                        'state_on': 'on',
                        'state_off': 'off',
                        'unique_id': f'{vin}_charging_start_stop'
                    }
                discovery_message['cmps'][f'{vin}_charging_connector_state'] = {
                    'p': 'sensor',
                    'device_class': 'enum',
                    'icon': 'mdi:ev-station',
                    'name': 'Charging Connector State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.connector.connection_state.get_absolute_path()}',
                    'unique_id': f'{vin}_charging_connector_state'
                }
                if vehicle.charging.connector.connection_state.value_type is not None \
                        and issubclass(vehicle.charging.connector.connection_state.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_charging_connector_state']['options'] = \
                        [item.value for item in vehicle.charging.connector.connection_state.value_type]
            if vehicle.charging.connector.lock_state.enabled and vehicle.charging.connector.lock_state.value is not None:
                discovery_message['cmps'][f'{vin}_charging_connector_lock_state'] = {
                    'p': 'binary_sensor',
                    'device_class': 'lock',
                    'icon': 'mdi:lock',
                    'name': 'Charging Connector Lock State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.connector.lock_state.get_absolute_path()}',
                    'payload_on': 'unlocked',
                    'payload_off': 'locked',
                    'unique_id': f'{vin}_charging_connector_lock_state'
                }
            if vehicle.charging.connector.external_power.enabled and vehicle.charging.connector.external_power.value is not None:
                discovery_message['cmps'][f'{vin}_charging_connector_external_power'] = {
                    'p': 'sensor',
                    'device_class': 'enum',
                    'icon': 'mdi:lightning-bolt',
                    'name': 'Charging Connector External Power',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.connector.external_power.get_absolute_path()}',
                    'unique_id': f'{vin}_charging_connector_external_power'
                }
                if vehicle.charging.connector.external_power.value_type is not None and issubclass(vehicle.charging.connector.external_power.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_charging_connector_external_power']['options'] = \
                        [item.value for item in vehicle.charging.connector.external_power.value_type]
            if vehicle.charging.state.enabled and vehicle.charging.state.value is not None:
                discovery_message['cmps'][f'{vin}_charging_state'] = {
                    'p': 'sensor',
                    'device_class': 'enum',
                    'icon': 'mdi:battery-charging',
                    'name': 'Charging State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.state.get_absolute_path()}',
                    'unique_id': f'{vin}_charging_state'
                }
                if vehicle.charging.state.value_type is not None and issubclass(vehicle.charging.state.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_charging_state']['options'] = [item.value for item in vehicle.charging.state.value_type]
            if vehicle.charging.type.enabled and vehicle.charging.type.value is not None:
                discovery_message['cmps'][f'{vin}_charging_type'] = {
                    'p': 'sensor',
                    'device_class': 'enum',
                    'icon': 'mdi:current-ac',
                    'name': 'Charging Type',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.type.get_absolute_path()}',
                    'unique_id': f'{vin}_charging_type'
                }
                if vehicle.charging.type.value_type is not None and issubclass(vehicle.charging.type.value_type, Enum):
                    discovery_message['cmps'][f'{vin}_charging_type']['options'] = [item.value for item in vehicle.charging.type.value_type]
            if vehicle.charging.rate.enabled and vehicle.charging.rate.value is not None and vehicle.charging.rate.unit is not None:
                discovery_message['cmps'][f'{vin}_charging_rate'] = {
                    'p': 'sensor',
                    'device_class': 'speed',
                    'icon': 'mdi:speedometer',
                    'name': 'Charging Rate',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.rate.get_absolute_path()}',
                    'unit_of_measurement': vehicle.charging.rate.unit.value,
                    'unique_id': f'{vin}_charging_rate'
                }
            if vehicle.charging.power.enabled and vehicle.charging.power.value is not None and vehicle.charging.power.unit is not None:
                discovery_message['cmps'][f'{vin}_charging_power'] = {
                    'p': 'sensor',
                    'device_class': 'power',
                    'icon': 'mdi:speedometer',
                    'name': 'Charging Power',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.power.get_absolute_path()}',
                    'unit_of_measurement': vehicle.charging.power.unit.value,
                    'unique_id': f'{vin}_charging_power'
                }
            if vehicle.charging.estimated_date_reached.enabled and vehicle.charging.estimated_date_reached.value is not None:
                discovery_message['cmps'][f'{vin}_charging_estimated_date_reached'] = {
                    'p': 'sensor',
                    'device_class': 'timestamp',
                    'icon': 'mdi:clock-end',
                    'name': 'Charging Estimated Date Reached',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.estimated_date_reached.get_absolute_path()}',
                    'unique_id': f'{vin}_charging_estimated_date_reached'
                }
            if vehicle.charging.settings is not None:
                if vehicle.charging.settings.target_level.enabled and vehicle.charging.settings.target_level.value is not None:
                    discovery_message['cmps'][f'{vin}_charging_target_level'] = {
                        'p': 'number',
                        'device_class': 'battery',
                        'icon': 'mdi:battery',
                        'name': 'Charging Target Level',
                        'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.target_level.get_absolute_path()}_writetopic',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.target_level.get_absolute_path()}',
                        'min': vehicle.charging.settings.target_level.minimum,
                        'max': vehicle.charging.settings.target_level.maximum,
                        'step': vehicle.charging.settings.target_level.precision,
                        'unit_of_measurement': vehicle.charging.settings.target_level.unit.value,
                        'unique_id': f'{vin}_charging_target_level'
                    }
                if vehicle.charging.settings.maximum_current.enabled and vehicle.charging.settings.maximum_current.value is not None:
                    discovery_message['cmps'][f'{vin}_charging_maximum_current'] = {
                        'p': 'number',
                        'device_class': 'power',
                        'icon': 'mdi:speedometer',
                        'name': 'Charging Maximum Current',
                        'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.maximum_current.get_absolute_path()}_writetopic',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.maximum_current.get_absolute_path()}',
                        'min': vehicle.charging.settings.maximum_current.minimum,
                        'max': vehicle.charging.settings.maximum_current.maximum,
                        'step': vehicle.charging.settings.maximum_current.precision,
                        'unit_of_measurement': vehicle.charging.settings.maximum_current.unit.value,
                        'unique_id': f'{vin}_charging_maximum_current'
                    }
                if vehicle.charging.settings.auto_unlock.enabled and vehicle.charging.settings.auto_unlock.value is not None:
                    discovery_message['cmps'][f'{vin}_charging_auto_unlock'] = {
                        'p': 'switch',
                        'name': 'Auto unlock charging connector',
                        'icon': 'mdi:lock',
                        'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.auto_unlock.get_absolute_path()}',
                        'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.charging.settings.auto_unlock.get_absolute_path()}_writetopic',
                        'payload_on': True,
                        'payload_off': False,
                        'state_on': True,
                        'state_off': False,
                        'unique_id': f'{vin}_charging_auto_unlock'
                    }
        if vehicle.position.enabled and vehicle.position.latitude.enabled and vehicle.position.latitude.value is not None \
                and vehicle.position.longitude.enabled and vehicle.position.longitude.value is not None:
            discovery_message['cmps'][f'{vin}_position'] = {
                'p': 'device_tracker',
                'icon': 'mdi:map-marker',
                'name': 'Position',
                'json_attributes_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.get_absolute_path()}/attributes',
                'source_type': 'gps',
                'unique_id': f'{vin}_position'
            }
        for sensor in discovery_message['cmps'].values():
            sensor['availability'] = [{
                'topic': f'{self.mqtt_plugin.mqtt_client.prefix}{self.mqtt_plugin.connection_state.get_absolute_path()}',
                'payload_not_available': 'disconnected',
                'payload_available': 'connected',
                }]
        discovery_hash = hash(json.dumps(discovery_message))
        if vin not in self.homeassistant_discovery_hashes or self.homeassistant_discovery_hashes[vin] != discovery_hash \
                or force:
            self.homeassistant_discovery_hashes[vin] = discovery_hash
            LOG.debug("Publishing Home Assistant discovery message for vehicle %s", vin)
            self.mqtt_plugin.mqtt_client.publish(topic=discovery_topic, qos=1, retain=False, payload=json.dumps(discovery_message, indent=4))

    def __send_position_extra_targets(self, position: Position) -> None:
        if self.mqtt_plugin is None:
            LOG.critical("MQTT plugin is None")
        elif position.latitude.enabled and position.latitude.value is not None \
                and position.longitude.enabled and position.longitude.value is not None:
            topic: str = f'{self.mqtt_plugin.mqtt_client.prefix}{position.get_absolute_path()}/attributes'
            #  pylint: disable-next=protected-access
            self.mqtt_plugin.mqtt_client._add_topic(topic=topic, with_filter=True, subscribe=False, writeable=False)
            payload: Dict[str, float] = {
                'latitude': position.latitude.value,
                'longitude': position.longitude.value
            }
            self.mqtt_plugin.mqtt_client.publish(topic=topic, qos=1, retain=False, payload=json.dumps(payload))

    def __send_charging_binary_state(self, charging_state: EnumAttribute[Charging.ChargingState]) -> None:
        if self.mqtt_plugin is None:
            LOG.critical("MQTT plugin is None")
        elif charging_state.enabled and charging_state.value is not None:
            topic: str = f'{self.mqtt_plugin.mqtt_client.prefix}{charging_state.parent.get_absolute_path()}/binarystate'
            #  pylint: disable-next=protected-access
            self.mqtt_plugin.mqtt_client._add_topic(topic=topic, with_filter=True, subscribe=False, writeable=False)
            payload: str = ''
            if charging_state.value in [Charging.ChargingState.CHARGING, Charging.ChargingState.CONSERVATION, Charging.ChargingState.DISCHARGING]:
                payload = 'on'
            elif charging_state.value in [Charging.ChargingState.OFF, Charging.ChargingState.READY_FOR_CHARGING, Charging.ChargingState.ERROR]:
                payload = 'off'
            self.mqtt_plugin.mqtt_client.publish(topic=topic, qos=1, retain=False, payload=payload)

    def __send_climatization_binary_state(self, climatization_state: EnumAttribute[Climatization.ClimatizationState]) -> None:
        if self.mqtt_plugin is None:
            LOG.critical("MQTT plugin is None")
        elif climatization_state.enabled and climatization_state.value is not None:
            topic: str = f'{self.mqtt_plugin.mqtt_client.prefix}{climatization_state.parent.get_absolute_path()}/binarystate'
            #  pylint: disable-next=protected-access
            self.mqtt_plugin.mqtt_client._add_topic(topic=topic, with_filter=True, subscribe=False, writeable=False)
            payload: str = ''
            if climatization_state.value in [Climatization.ClimatizationState.HEATING,
                                             Climatization.ClimatizationState.COOLING,
                                             Climatization.ClimatizationState.VENTILATION]:
                payload = 'on'
            elif climatization_state.value in [Climatization.ClimatizationState.OFF]:
                payload = 'off'
            self.mqtt_plugin.mqtt_client.publish(topic=topic, qos=1, retain=False, payload=payload)

    def __send_climatization_hvac_topics(self, climatization_state: EnumAttribute[Climatization.ClimatizationState]) -> None:
        if self.mqtt_plugin is None:
            LOG.critical("MQTT plugin is None")
        elif climatization_state.enabled and climatization_state.value is not None:
            action_topic: str = f'{self.mqtt_plugin.mqtt_client.prefix}{climatization_state.parent.get_absolute_path()}/hvac_action'
            mode_topic: str = f'{self.mqtt_plugin.mqtt_client.prefix}{climatization_state.parent.get_absolute_path()}/hvac_mode'
            #  pylint: disable-next=protected-access
            self.mqtt_plugin.mqtt_client._add_topic(topic=action_topic, with_filter=True, subscribe=False, writeable=False)
            #  pylint: disable-next=protected-access
            self.mqtt_plugin.mqtt_client._add_topic(topic=mode_topic, with_filter=True, subscribe=False, writeable=False)
            action_payload: str = ''
            mode_payload: str = ''
            if climatization_state.value == Climatization.ClimatizationState.HEATING:
                action_payload = 'heating'
                mode_payload = 'auto'
            elif climatization_state.value == Climatization.ClimatizationState.COOLING:
                action_payload = 'cooling'
                mode_payload = 'auto'
            elif climatization_state.value == Climatization.ClimatizationState.VENTILATION:
                action_payload = 'fan'
                mode_payload = 'auto'
            elif climatization_state.value in [Climatization.ClimatizationState.OFF]:
                action_payload = 'off'
                mode_payload = 'off'
            self.mqtt_plugin.mqtt_client.publish(topic=action_topic, qos=1, retain=False, payload=action_payload)
            self.mqtt_plugin.mqtt_client.publish(topic=mode_topic, qos=1, retain=False, payload=mode_payload)

    def _on_carconnectivity_event(self, element, flags) -> None:
        """
        Callback for car connectivity events.
        On enable of an attribute it will republish the device discovery message.

        Args:
            element (Observable): The element that triggered the event.
            flags (Observable.ObserverEvent): The event flags.

        Returns:
            None
        """
        # An attribute is enabled
        if flags & Observable.ObserverEvent.ENABLED:
            self._publish_homeassistant_discovery()
        if flags & (Observable.ObserverEvent.ENABLED | Observable.ObserverEvent.VALUE_CHANGED):
            if self.mqtt_plugin is None:
                LOG.critical("MQTT plugin is None")
            else:
                # Generate position topic with latitude and longitude in same payload
                if isinstance(element, FloatAttribute) and element.id == 'longitude' and element.value is not None \
                        and isinstance(element.parent, Position):
                    self.__send_position_extra_targets(element.parent)
                elif isinstance(element, EnumAttribute) and element.id == 'state' and element.value_type == Charging.ChargingState:
                    self.__send_charging_binary_state(element)
                elif isinstance(element, EnumAttribute) and element.id == 'state' and element.value_type == Climatization.ClimatizationState:
                    self.__send_climatization_binary_state(element)
                    self.__send_climatization_hvac_topics(element)

    def _on_message_callback(self, mqttc, obj, msg) -> None:  # noqa: C901
        """
        Callback for receiving a message from the MQTT broker.

        It will publish the discovery messages on receiving a 'online' message on homeassistant/status messages

        Args:
            mqttc (paho.mqtt.client.Client): unused
            obj (Any): unused
            msg (paho.mqtt.client.MQTTMessage): The message received from the broker.

        Returns:
            None
        """
        del mqttc
        del obj
        if msg.topic == f'{self.active_config["homeassistant_prefix"]}/status':
            if self.homeassistant_discovery and msg.payload.lower() == b'online':
                self._publish_homeassistant_discovery(force=True)

    # pylint: disable-next=too-many-arguments, too-many-positional-arguments
    def _on_connect_callback(self, mqttc, obj, flags, reason_code, properties) -> None:  # noqa: C901
        """
        Callback for connection to the MQTT broker.
        On successful connection it will publish the discovery messages

        Args:
            mqttc (paho.mqtt.client.Client): unused
            obj (Any): unused
            flags (Any): unused
            reason_code (int): unused
            properties (Any): unused

        Returns:
            None
        """
        del mqttc
        del obj
        del flags
        del properties
        # reason_code 0 means success
        if reason_code == 0:
            if self.homeassistant_discovery:
                if self.mqtt_plugin is not None:
                    self.mqtt_plugin.mqtt_client.subscribe('homeassistant/status', qos=1)
                    self._publish_homeassistant_discovery(force=True)
            # send extra topics after connection
            for vehicle in self.car_connectivity.garage.list_vehicles():
                if vehicle.enabled:
                    if vehicle.position.enabled and vehicle.position.latitude.enabled and vehicle.position.latitude.value is not None \
                            and vehicle.position.longitude.enabled and vehicle.position.longitude.value is not None:
                        self.__send_position_extra_targets(vehicle.position)
                    if isinstance(vehicle, ElectricVehicle) and vehicle.charging.state.enabled and vehicle.charging.state.value is not None:
                        self.__send_charging_binary_state(vehicle.charging.state)
                    if vehicle.climatization.state.enabled and vehicle.climatization.state.value is not None:
                        self.__send_climatization_binary_state(vehicle.climatization.state)
                        self.__send_climatization_hvac_topics(vehicle.climatization.state)
