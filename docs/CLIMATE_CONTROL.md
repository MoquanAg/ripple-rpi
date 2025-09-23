# Climate Control System Documentation

## Overview

The Ripple fertigation system includes comprehensive climate control functionality that manages environmental conditions for optimal plant growth. This system operates similarly to HVAC (Heating, Ventilation, Air Conditioning) systems but is specifically designed for vertical farming applications.

## Climate Control Parameters

### Temperature Control

#### Ambient Temperature Management
- **Day Temperature Range**: 16°C - 24°C (configurable)
- **Night Temperature Range**: 15°C - 20°C (configurable)
- **Deadband**: 1°C (prevents rapid switching)
- **Priority Control**: Temperature-based VPD (Vapor Pressure Deficit) management

#### Water Temperature Control
- **Target Temperature**: 18°C (configurable)
- **Temperature Range**: 18°C - 18°C (can be expanded)
- **Control Method**: Mixing pump and heating/cooling systems

### Humidity Control

#### Relative Humidity (RH) Management
- **Day RH Range**: 50% - 70% (0.5 - 0.7)
- **Night RH Range**: 40% - 80% (0.4 - 0.8)
- **Deadband**: 
  - Day: 10% (0.1)
  - Night: 20% (0.2)
- **Target Values**:
  - Day: 60% (0.6)
  - Night: 60% (0.6)

### CO2 Management

#### Carbon Dioxide Control
- **Day CO2 Range**: 800 ppm (configurable)
- **Night CO2 Range**: 800 ppm (configurable)
- **Target Values**:
  - Day: 800 ppm
  - Night: 800 ppm
- **Control Method**: CO2 injection system

### Vapor Pressure Deficit (VPD)

#### VPD Priority Control
- **Day Priority**: Temperature-based control
- **Night Priority**: Temperature-based control
- **Purpose**: Optimizes plant transpiration and nutrient uptake

## System Integration

### Control Hierarchy
1. **Primary Control**: Temperature management
2. **Secondary Control**: Humidity regulation
3. **Tertiary Control**: CO2 supplementation
4. **Integrated Control**: VPD optimization

### Day/Night Cycle Management
- **Automatic Switching**: Based on lighting schedules
- **Offset Configuration**: Configurable start/end times
- **Smooth Transitions**: Gradual parameter changes

## API Integration

### Server Instruction Sets
Climate control parameters are received through server instruction sets in the `action_climate` section:

```json
{
  "action_climate": {
    "id": 3,
    "vpd_priority_day": "temp",
    "vpd_priority_night": "temp",
    "target_rh_max_day": 0.7,
    "target_rh_max_night": 0.8,
    "target_rh_min_night": 0.4,
    "target_rh_min_day": 0.5,
    "target_rh_deadband_day": 0.1,
    "target_rh_deadband_night": 0.2,
    "target_co2_max_day": 800,
    "target_co2_max_night": 800,
    "target_co2_min_night": 800,
    "target_co2_min_day": 800,
    "target_amb_temp_max_day": 24,
    "target_amb_temp_max_night": 20,
    "target_amb_temp_min_day": 16,
    "target_amb_temp_min_night": 15,
    "target_amb_temp_deadband_day": 1,
    "target_amb_temp_deadband_night": 1,
    "target_amb_temp_day_starting_offset": "+00:00:00",
    "target_amb_temp_day_ending_offset": "+00:00:00",
    "target_amb_temp_night_ending_offset": "+00:00:00",
    "target_amb_temp_night_starting_offset": "+00:00:00",
    "target_rh_day": 0.6,
    "target_rh_night": 0.6,
    "target_co2_day": 800,
    "target_co2_night": 800,
    "target_amb_temp_day": 20,
    "target_amb_temp_night": 18
  }
}
```

## Hardware Integration

### Temperature Control Hardware
- **Heating Elements**: For temperature increase
- **Cooling Systems**: For temperature decrease
- **Mixing Pumps**: For water temperature regulation
- **Temperature Sensors**: For feedback control

### Humidity Control Hardware
- **Humidifiers**: For humidity increase
- **Dehumidifiers**: For humidity decrease
- **Ventilation Fans**: For air circulation
- **Humidity Sensors**: For feedback control

### CO2 Control Hardware
- **CO2 Injectors**: For CO2 supplementation
- **CO2 Sensors**: For concentration monitoring
- **Valves**: For precise CO2 delivery

## Control Algorithms

### PID Control
- **Temperature**: Proportional-Integral-Derivative control for smooth temperature regulation
- **Humidity**: PID control with deadband to prevent oscillation
- **CO2**: On/off control with safety limits

### VPD Calculation
```
VPD = (1 - RH/100) * SVP(T)
```
Where:
- RH = Relative Humidity (%)
- SVP(T) = Saturation Vapor Pressure at temperature T

### Safety Limits
- **Temperature Limits**: Hardware safety switches
- **Humidity Limits**: Condensation prevention
- **CO2 Limits**: Safety shutoff at high concentrations

## Monitoring and Logging

### Data Collection
- **Sensor Readings**: Continuous monitoring of all parameters
- **Control Actions**: Logging of all control decisions
- **System Status**: Health monitoring of all components

### Alerts and Notifications
- **Parameter Drift**: When values exceed acceptable ranges
- **Hardware Failures**: Component malfunction detection
- **Safety Violations**: Critical parameter breaches

## Configuration Management

### Device Configuration
Climate control parameters are stored in the device configuration file with the following structure:

```ini
[ClimateControl]
target_amb_temp_day = 20.0, 20.0
target_amb_temp_night = 18.0, 18.0
target_rh_day = 0.6, 0.6
target_rh_night = 0.6, 0.6
target_co2_day = 800, 800
target_co2_night = 800, 800
```

### Dynamic Updates
- **Hot Reloading**: Configuration changes without system restart
- **Server Updates**: Remote parameter updates via instruction sets
- **Manual Override**: Local parameter adjustments

## Troubleshooting

### Common Issues
1. **Temperature Drift**: Check heating/cooling system operation
2. **Humidity Oscillation**: Adjust deadband values
3. **CO2 Concentration**: Verify injection system and sensors
4. **VPD Imbalance**: Check temperature and humidity coordination

### Maintenance
- **Sensor Calibration**: Regular calibration of all sensors
- **Filter Replacement**: Air filtration system maintenance
- **System Cleaning**: Regular cleaning of control components
- **Software Updates**: Keep control algorithms updated

## Future Enhancements

### Planned Features
- **Machine Learning**: Adaptive control algorithms
- **Predictive Control**: Weather-based parameter adjustment
- **Energy Optimization**: Efficiency-focused control strategies
- **Remote Monitoring**: Cloud-based system monitoring

### Integration Opportunities
- **Weather APIs**: External weather data integration
- **Energy Management**: Power consumption optimization
- **Crop Models**: Plant-specific parameter optimization
- **Automation**: Fully autonomous climate control

---

*This documentation covers the climate control functionality of the Ripple fertigation system, providing comprehensive information for system operation, maintenance, and development.*









