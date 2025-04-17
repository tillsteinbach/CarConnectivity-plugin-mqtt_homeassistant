# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
- No unreleased changes so far

## [0.4] - 2025-04-17
### Added
- state_class attribute added to all entities this value is relevant for

### Changed
- Updated dependencies

## [0.3] - 2025-04-02
### Fixed
- Allowes to have multiple instances of this plugin running
- Correct unit based on locale in mqtt plugin
- Setting retain flag on homeassistant specific topics

### Changed
- Updated dependencies

## [0.2] - 2025-03-20
### Added
- Set correct device class
- Added adblue_level
- Added adblue_range
- Added controls for window heating
- Added controls for charging settings

## [0.1.1] - 2025-03-10
### Fixed
- Fixed bug that lead to device tracker not being announced for non electric vehicles

## [0.1] - 2025-03-02
Initial release, let's go and give this to the public to try out...
Most attributes are provided as entities in Auto discovery mode.
Support for MQTT Lock ans MQTT HAVC is provided.

[unreleased]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/compare/v0.4...HEAD
[0.4]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/tag/v0.4
[0.3]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/tag/v0.3
[0.2]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/tag/v0.2
[0.1.1]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/tag/v0.1.1
[0.1]: https://github.com/tillsteinbach/CarConnectivity-plugin-mqtt_homeassistant/releases/tag/v0.1
