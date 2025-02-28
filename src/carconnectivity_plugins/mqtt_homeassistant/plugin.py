"""Module implements the plugin to improve compatibility with Home Assistant."""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
import json

from carconnectivity.util import config_remove_credentials
from carconnectivity.vehicle import GenericVehicle
from carconnectivity.drive import ElectricDrive, CombustionDrive
from carconnectivity.observable import Observable

from carconnectivity_plugins.base.plugin import BasePlugin

from carconnectivity_plugins.mqtt.plugin import Plugin as MqttPlugin

from carconnectivity_plugins.mqtt_homeassistant._version import __version__

if TYPE_CHECKING:
    from typing import Dict, Optional
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
        self._is_healthy = True
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
            LOG.error("MQTT plugin not found, MQTT Home Assistant plugin will not work")
            self._is_healthy = False
        if not isinstance(self.car_connectivity.plugins.plugins['mqtt'], MqttPlugin):
            LOG.error("MQTT plugin is not an instance of MqttPlugin, MQTT Home Assistant plugin will not work")
            self._is_healthy = False
        else:
            self.mqtt_plugin = self.car_connectivity.plugins.plugins['mqtt']

        if self.mqtt_plugin is None:
            LOG.error("MQTT plugin is None, MQTT Home Assistant plugin will not work")
            self._is_healthy = False
        else:
            self.mqtt_plugin.mqtt_client.add_on_message_callback(self._on_message_callback)
            self.mqtt_plugin.mqtt_client.add_on_connect_callback(self._on_connect_callback)

        flags: Observable.ObserverEvent = Observable.ObserverEvent.ENABLED | Observable.ObserverEvent.DISABLED
        self.car_connectivity.add_observer(self._on_carconnectivity_event, flags, priority=Observable.ObserverPriority.USER_MID)

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

    def is_healthy(self) -> bool:
        """
        Returns whether the plugin is healthy.

        Returns:
            bool: True if the connector is healthy, False otherwise.
        """
        return self._is_healthy

    def _publish_homeassistant_discovery(self, force=False) -> None:
        for vehicle in self.car_connectivity.garage.list_vehicles():
            if vehicle.enabled:
                self._publish_homeassistant_discovery_vehicle(vehicle, force=force)

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
        discovery_topic = f'{self.active_config['homeassistant_prefix']}/device/{vin}/config'
        discovery_message = {
            'device': {
                'ids': vin,
                'sn': vin,
                'availability_topic': f'{self.mqtt_plugin.mqtt_client.prefix}/plugins/{self.mqtt_plugin.mqtt_client.plugin_id}/connected',
                'payload_not_available': 'False',
                'payload_available': 'True',
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

        if vehicle.odometer.enabled and vehicle.odometer.value is not None and vehicle.odometer.unit is not None:
            discovery_message['cmps'][f'{vin}_odometer'] = {
                'p': 'sensor',
                'device_class': 'distance',
                'name': 'Odometer',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.odometer.get_absolute_path()}',
                'unit_of_measurement': vehicle.odometer.unit.value,
                'unique_id': f'{vin}_odometer'
            }
        if vehicle.state.enabled and vehicle.state.value is not None:
            discovery_message['cmps'][f'{vin}_state'] = {
                'p': 'sensor',
                'name': 'Vehicle State',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.state.get_absolute_path()}',
                'unique_id': f'{vin}_state'
            }
        if vehicle.connection_state.enabled and vehicle.connection_state.value is not None:
            discovery_message['cmps'][f'{vin}_connection_state'] = {
                'p': 'sensor',
                'name': 'Connection State',
                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.connection_state.get_absolute_path()}',
                'unique_id': f'{vin}_connection_state'
            }
        if vehicle.drives is not None and vehicle.drives.enabled:
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
                                'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.level.get_absolute_path()}',
                                'unit_of_measurement': drive.level.unit.value,
                                'unique_id': f'{vin}_{drive_id}_level'
                            }
                    elif isinstance(drive, ElectricDrive):
                        if drive.level.enabled and drive.level.value is not None and drive.level.unit is not None:
                            discovery_message['cmps'][f'{vin}_{drive_id}_level'] = {
                                'p': 'sensor',
                                'device_class': 'battery',
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
                                    'name': f'Battery Temperature ({drive_id})',
                                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{drive.battery.temperature.get_absolute_path()}',
                                    'unit_of_measurement': drive.battery.temperature.unit.value,
                                    'unique_id': f'{vin}_{drive_id}_battery_temperature'
                                }
        if vehicle.doors is not None and vehicle.doors.enabled:
            if vehicle.doors.open_state.enabled and vehicle.doors.open_state.value is not None:
                discovery_message['cmps'][f'{vin}_open_state'] = {
                    'p': 'binary_sensor',
                    'name': 'Open State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.open_state.get_absolute_path()}',
                    'payload_off': 'closed',
                    'payload_on': 'open',
                    'unique_id': f'{vin}_open_state'
                }
            if vehicle.doors.lock_state.enabled and vehicle.doors.lock_state.value is not None:
                discovery_message['cmps'][f'{vin}_lock_state'] = {
                    'p': 'binary_sensor',
                    'name': 'Lock State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.doors.lock_state.get_absolute_path()}',
                    'payload_off': 'unlocked',
                    'payload_on': 'locked',
                    'unique_id': f'{vin}_lock_state'
                }
            for door_id, door in vehicle.doors.doors.items():
                if door.enabled:
                    if door.open_state.enabled and door.open_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{door_id}_open_state'] = {
                            'p': 'binary_sensor',
                            'name': f'Open State ({door_id})',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{door.open_state.get_absolute_path()}',
                            'payload_off': 'closed',
                            'payload_on': 'open',
                            'unique_id': f'{vin}_{door_id}_open_state'
                        }
                    if door.lock_state.enabled and door.lock_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{door_id}_lock_state'] = {
                            'p': 'binary_sensor',
                            'name': f'Lock State ({door_id})',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{door.lock_state.get_absolute_path()}',
                            'payload_off': 'unlocked',
                            'payload_on': 'locked',
                            'unique_id': f'{vin}_{door_id}_lock_state'
                        }
        if vehicle.windows is not None and vehicle.windows.enabled:
            if vehicle.windows.open_state.enabled and vehicle.windows.open_state.value is not None:
                discovery_message['cmps'][f'{vin}_open_state'] = {
                    'p': 'binary_sensor',
                    'name': 'Open State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.windows.open_state.get_absolute_path()}',
                    'payload_off': 'closed',
                    'payload_on': 'open',
                    'unique_id': f'{vin}_open_state'
                }
            for window_id, window in vehicle.windows.windows.items():
                if window.enabled:
                    if window.open_state.enabled and window.open_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{window_id}_open_state'] = {
                            'p': 'binary_sensor',
                            'name': f'Open State ({window_id})',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{window.open_state.get_absolute_path()}',
                            'payload_off': 'closed',
                            'payload_on': 'open',
                            'unique_id': f'{vin}_{window_id}_open_state'
                        }
        if vehicle.lights is not None and vehicle.lights.enabled:
            if vehicle.lights.light_state.enabled and vehicle.lights.light_state.value is not None:
                discovery_message['cmps'][f'{vin}_light_state'] = {
                    'p': 'sensor',
                    'name': 'Light State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.lights.light_state.get_absolute_path()}',
                    'payload_off': 'off',
                    'payload_on': 'on',
                    'unique_id': f'{vin}_light_state'
                }
            for light_id, light in vehicle.lights.lights.items():
                if light.enabled:
                    if light.light_state.enabled and light.light_state.value is not None:
                        discovery_message['cmps'][f'{vin}_{light_id}_state'] = {
                            'p': 'sensor',
                            'name': f'Light State ({light_id})',
                            'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{light.light_state.get_absolute_path()}',
                            'payload_off': 'off',
                            'payload_on': 'on',
                            'unique_id': f'{vin}_{light_id}_state'
                        }
        if vehicle.position.enabled:
            if vehicle.position.latitude.enabled and vehicle.position.latitude.value is not None \
                    and vehicle.position.longitude.enabled and vehicle.position.longitude.value is not None \
                    and vehicle.position.latitude.unit is not None and vehicle.position.longitude.unit is not None:
                discovery_message['cmps'][f'{vin}_latitude'] = {
                    'p': 'sensor',
                    'name': 'Position Latitude',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.latitude.get_absolute_path()}',
                    'unit_of_measurement': vehicle.position.latitude.unit.value,
                    'unique_id': f'{vin}_latitude'
                }
                discovery_message['cmps'][f'{vin}_longitude'] = {
                    'p': 'sensor',
                    'name': 'Position Longitude',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.longitude.get_absolute_path()}',
                    'unit_of_measurement': vehicle.position.longitude.unit.value,
                    'unique_id': f'{vin}_longitude'
                }
            if vehicle.position.position_type.enabled and vehicle.position.position_type.value is not None:
                discovery_message['cmps'][f'{vin}_position_type'] = {
                    'p': 'sensor',
                    'name': 'Position Type',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.position.position_type.get_absolute_path()}',
                    'unique_id': f'{vin}_position_type'
                }
        if vehicle.climatization.enabled:
            if vehicle.climatization.state.enabled and vehicle.climatization.state.value is not None:
                discovery_message['cmps'][f'{vin}_climatization_state'] = {
                    'p': 'sensor',
                    'name': 'Climatization State',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.state.get_absolute_path()}',
                    'unique_id': f'{vin}_climatization_state'
                }
            if vehicle.climatization.commands.enabled and 'start-stop' in vehicle.climatization.commands.commands:
                discovery_message['cmps'][f'{vin}_climatization_start_stop'] = {
                    'p': 'switch',
                    'name': 'Start/Stop Climatization',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.state.get_absolute_path()}',
                    'command_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.climatization.commands.commands['start-stop'].get_absolute_path()}'
                    + '_writetopic',
                    'payload_on': 'start',
                    'payload_off': 'stop',
                    'state_on': ['heating', 'cooling', 'ventilation'],
                    'state_off': 'off',
                    'unique_id': f'{vin}_climatization_start_stop'
                }
        if vehicle.outside_temperature.enabled and vehicle.outside_temperature.value is not None and vehicle.outside_temperature.unit is not None:
            discovery_message['cmps'][f'{vin}_outside_temperature'] = {
                'p': 'sensor',
                'device_class': 'temperature',
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
                    'name': 'Inspection Due At',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.inspection_due_at.get_absolute_path()}',
                    'unique_id': f'{vin}_inspection_due_at'
                }
            if vehicle.maintenance.inspection_due_after.enabled and vehicle.maintenance.inspection_due_after.value is not None \
                    and vehicle.maintenance.inspection_due_after.unit is not None:
                discovery_message['cmps'][f'{vin}_inspection_due_after'] = {
                    'p': 'sensor',
                    'device_class': 'distance',
                    'name': 'Inspection Due After',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.inspection_due_after.get_absolute_path()}',
                    'unit_of_measurement': vehicle.maintenance.inspection_due_after.unit.value,
                    'unique_id': f'{vin}_inspection_due_after'
                }
            if vehicle.maintenance.oil_service_due_at.enabled and vehicle.maintenance.oil_service_due_at.value is not None:
                discovery_message['cmps'][f'{vin}_oil_service_due_at'] = {
                    'p': 'sensor',
                    'device_class': 'timestamp',
                    'name': 'Oil Service Due At',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.oil_service_due_at.get_absolute_path()}',
                    'unique_id': f'{vin}_oil_service_due_at'
                }
            if vehicle.maintenance.oil_service_due_after.enabled and vehicle.maintenance.oil_service_due_after.value is not None \
                    and vehicle.maintenance.oil_service_due_after.unit is not None:
                discovery_message['cmps'][f'{vin}_oil_service_due_after'] = {
                    'p': 'sensor',
                    'device_class': 'distance',
                    'name': 'Oil Service Due After',
                    'state_topic': f'{self.mqtt_plugin.mqtt_client.prefix}{vehicle.maintenance.oil_service_due_after.get_absolute_path()}',
                    'unit_of_measurement': vehicle.maintenance.oil_service_due_after.unit.value,
                    'unique_id': f'{vin}_oil_service_due_after'
                }
        # if SUPPORT_IMAGES and self.image_format == ImageFormat.PNG:
        #     if vehicle.images.enabled:
        #         for image_id, image in vehicle.images.images.items():
        #             if image.enabled and image.value is not None:
        #                 discovery_message['cmps'][f'{vin}_{image_id}_image'] = {
        #                     'p': 'entity_picture',
        #                     'name': f'Image ({image_id})',
        #                     'topic': f'{self.prefix}{image.get_absolute_path()}',
        #                     'unique_id': f'{vin}_{image_id}_image'
        #                 }
        if vin not in self.homeassistant_discovery_hashes or self.homeassistant_discovery_hashes[vin] != hash(json.dumps(discovery_message)) \
                or force:
            self.homeassistant_discovery_hashes[vin] = hash(json.dumps(discovery_message))
            LOG.debug("Publishing Home Assistant discovery message for vehicle %s", vin)
            self.mqtt_plugin.mqtt_client.publish(topic=discovery_topic, qos=1, retain=False, payload=json.dumps(discovery_message, indent=4))

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
        del element  # Unused
        # An attribute is enabled
        if flags & Observable.ObserverEvent.ENABLED:
            self._publish_homeassistant_discovery()

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
        if msg.topic == f'{self.active_config['homeassistant_prefix']}/status':
            if self.homeassistant_discovery and msg.payload.lower() == b'online':
                self._publish_homeassistant_discovery(force=True)

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
